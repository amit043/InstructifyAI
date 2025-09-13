def test_detect_hardware_keys():
    from core.hw import detect_hardware

    info = detect_hardware()

    # Required keys exist
    for key in [
        "has_cuda",
        "gpu_name",
        "vram_mb",
        "cuda_cc",
        "cpu_cores",
        "ram_gb",
    ]:
        assert key in info, f"missing key: {key}"

    # Basic type checks that won't be environment-specific
    assert isinstance(info["has_cuda"], bool)
    assert isinstance(info["cpu_cores"], int) and info["cpu_cores"] >= 1
    assert isinstance(info["ram_gb"], float)

    # GPU fields are optional; if CUDA is present, name may be provided
    if info["has_cuda"]:
        # Name and VRAM could still be None if toolchain is partially available;
        # we don't assert here to avoid false negatives in CI without NVML.
        pass

