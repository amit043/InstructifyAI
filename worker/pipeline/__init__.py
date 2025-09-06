from core.settings import get_settings
from models import Project

settings = get_settings()


def get_parser_settings(project: Project) -> dict[str, object]:
    return {
        "ocr_langs": project.ocr_langs or settings.ocr_langs,
        "min_text_len_for_ocr": project.min_text_len_for_ocr
        or settings.min_text_len_for_ocr,
        "html_crawl_limits": project.html_crawl_limits
        or {
            "max_depth": settings.html_crawl_max_depth,
            "max_pages": settings.html_crawl_max_pages,
        },
        # V2-specific toggles (with sane defaults if attributes missing)
        "download_images": getattr(project, "download_images", True),
        "max_image_bytes": getattr(project, "max_image_bytes", 2_000_000),
        "chunk_token_target": getattr(project, "chunk_token_target", 1200),
        "chunk_token_overlap": getattr(project, "chunk_token_overlap", 200),
    }


__all__ = ["get_parser_settings"]
