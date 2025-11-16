from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

try:
    from instructifyai._internal.repo_paths import get_repo_root
except Exception:  # pragma: no cover - fallback for ad-hoc environments
    def get_repo_root() -> Path:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=True,
            )
            return Path(completed.stdout.strip())
        except Exception:
            cwd = Path.cwd()
            return cwd.parent if cwd.name.lower() == "notebooks" else cwd


from api.db import SessionLocal
from retrieval.service import retrieve_evidence
from scripts.serve_local import ModelService, _build_grounded_prompt

NOTEBOOK_MODEL_SERVICE = ModelService()


def _coerce_python_candidate(spec: Optional[str]) -> Optional[str]:
    if not spec:
        return None
    path_candidate = Path(spec)
    if path_candidate.exists():
        return str(path_candidate)
    resolved = shutil.which(spec)
    if resolved:
        return resolved
    return None


def _resolve_python_executable(spec: Optional[str], repo_root: Path) -> str:
    user_candidate = _coerce_python_candidate(spec)
    candidates: list[str] = []
    if user_candidate:
        candidates.append(user_candidate)
    fallback = _coerce_python_candidate(sys.executable) or sys.executable
    if fallback not in candidates:
        candidates.append(fallback)

    last_error: Optional[str] = None
    for candidate in candidates:
        try:
            subprocess.run(
                [candidate, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(repo_root),
                check=True,
            )
            if user_candidate and candidate != user_candidate:
                print(
                    "[notebook_runner] TRAINING_CONFIG['python'] "
                    f"{user_candidate!r} was unavailable; falling back to {candidate!r}."
                )
            return candidate
        except (FileNotFoundError, PermissionError) as exc:
            last_error = f"{candidate} not runnable: {exc}"
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or "").strip()
            msg = err or str(exc)
            last_error = f"{candidate} failed sanity check: {msg}"
        except OSError as exc:
            last_error = f"{candidate} could not start: {exc}"

    raise RuntimeError(
        "Unable to locate a runnable python interpreter."
        + (f" Last error: {last_error}" if last_error else "")
    )


def _build_training_cmd(cfg: dict[str, Any]) -> tuple[list[str], Path, Path, Path]:
    repo_root = get_repo_root()
    script_path = (repo_root / "scripts" / "train_adapter.py").resolve()
    if not script_path.exists():
        raise FileNotFoundError(f"train_adapter.py not found at: {script_path}")

    ds = Path(cfg["dataset_path"]).expanduser()
    dataset_path = (ds if ds.is_absolute() else repo_root / ds).resolve()
    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset_path not found: {dataset_path}")

    out = Path(cfg.get("output_dir", "outputs/notebook_adapter")).expanduser()
    output_dir = (out if out.is_absolute() else repo_root / out).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    python_exe = _resolve_python_executable(cfg.get("python"), repo_root)

    cmd = [
        python_exe,
        str(script_path),
        "--mode",
        cfg["mode"],
        "--project-id",
        cfg["project_id"],
        "--base-model",
        cfg["base_model"],
        "--data",
        str(dataset_path),
        "--output-dir",
        str(output_dir),
        "--epochs",
        str(cfg.get("epochs", 1)),
        "--lr",
        str(cfg.get("lr", 2e-4)),
        "--batch-size",
        str(cfg.get("batch_size", 1)),
        "--grad-accum",
        str(cfg.get("grad_accum", 8)),
        "--max-seq-len",
        str(cfg.get("max_seq_len", 1024)),
        "--quantization",
        cfg.get("quantization", "int4"),
        "--peft",
        cfg.get("peft", "dora"),
    ]
    doc_id = cfg.get("document_id")
    if doc_id:
        cmd += ["--document-id", doc_id]
    return cmd, dataset_path, output_dir, repo_root


def run_training_job(cfg: dict[str, Any]) -> dict[str, Any]:
    cmd, _, output_dir, repo_root = _build_training_cmd(cfg)
    print("Running:", shlex.join(cmd))
    payload: dict[str, Any] | None = None
    log_path = output_dir / "notebook_train.log"
    log_tail: list[str] = []
    max_tail = 400

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root)

    proc = subprocess.Popen(
        cmd,
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            for line in proc.stdout:
                print(line, end="")
                log_file.write(line)
                log_tail.append(line)
                if len(log_tail) > max_tail:
                    log_tail.pop(0)
                stripped = line.strip()
                if stripped.startswith("{") and stripped.endswith("}"):
                    try:
                        candidate = json.loads(stripped)
                        if isinstance(candidate, dict) and "artifact" in candidate:
                            payload = candidate
                    except json.JSONDecodeError:
                        pass
    finally:
        proc.stdout.close()
    code = proc.wait()
    if code != 0:
        tail = "".join(log_tail[-20:])
        raise RuntimeError(f"training exited with code {code} Last_lines: {tail}")
    return {
        "result": payload,
        "output_dir": str(output_dir),
        "log_path": str(log_path),
        "log_tail": log_tail,
    }


def ensure_adapter_dir(cfg: dict[str, Any]) -> Path:
    repo_root = get_repo_root()
    out = Path(cfg.get("output_dir", "outputs/notebook_adapter")).expanduser()
    output_dir = (out if out.is_absolute() else repo_root / out).resolve()
    if not output_dir.exists():
        raise FileNotFoundError(
            f"Adapter directory {output_dir} not found. Train first or update TRAINING_CONFIG."
        )
    return output_dir


def ask_with_adapter(
    ask_cfg: dict[str, Any], *, adapter_dir: Path, manual_context: Optional[list[str]] = None
) -> dict[str, Any]:
    question = ask_cfg["question"]
    project_id = ask_cfg["project_id"]
    document_id = ask_cfg.get("document_id")
    top_k = int(ask_cfg.get("top_k", 3))
    temperature = float(ask_cfg.get("temperature", 0.0))
    max_new_tokens = int(ask_cfg.get("max_new_tokens", 400))
    base_model = ask_cfg.get("base_model")

    if not base_model:
        raise ValueError("ask_cfg['base_model'] is required to load the adapter.")

    if manual_context:
        evidence = [
            {
                "chunk_id": f"manual-{idx}",
                "doc_id": document_id,
                "text": text,
                "section_path": [],
                "order": idx,
                "score": 1.0,
                "rank_score": 1.0,
            }
            for idx, text in enumerate(manual_context)
        ]
    else:
        with SessionLocal() as db:
            evidence = retrieve_evidence(
                db,
                project_id=project_id,
                document_id=document_id,
                prompt=question,
                top_k=top_k,
            )

    prompt, system_prompt, citations = _build_grounded_prompt(question, evidence)
    NOTEBOOK_MODEL_SERVICE.ensure_loaded(
        base_model_override=base_model,
        adapter_dir=str(adapter_dir),
    )
    answer = NOTEBOOK_MODEL_SERVICE.generate(
        prompt,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        system_prompt=system_prompt,
    )
    return {
        "answer": answer.strip(),
        "citations": citations,
        "prompt": prompt,
        "system_prompt": system_prompt,
        "evidence": evidence,
    }
