from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import urllib.request
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS_DIR = PROJECT_ROOT / "backend" / "models"
DEFAULT_MANIFEST_PATH = DEFAULT_MODELS_DIR / "manifest.json"


def load_manifest(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    with manifest_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("models", {})


def compute_file_hashes(path: Path) -> tuple[str, str]:
    sha256 = hashlib.sha256()
    md5 = hashlib.md5()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            sha256.update(chunk)
            md5.update(chunk)
    return sha256.hexdigest().lower(), md5.hexdigest().lower()


def verify_lama_file(path: Path, entry: dict[str, Any]) -> tuple[bool, str]:
    if not path.is_file():
        return False, "chưa tồn tại"
    size = path.stat().st_size
    if size < 50 * 1024 * 1024:
        return False, f"kích thước bất thường ({size} bytes)"

    expected_sha = (entry.get("sha256") or "").lower()
    expected_md5 = (entry.get("fallback_md5") or "").lower()
    if not expected_sha and not expected_md5:
        return True, f"hợp lệ ({size} bytes)"

    actual_sha, actual_md5 = compute_file_hashes(path)
    if expected_sha and actual_sha == expected_sha:
        return True, f"SHA256 khớp ({actual_sha[:12]}...)"
    if expected_md5 and actual_md5 == expected_md5:
        return True, f"MD5 mirror khớp ({actual_md5[:12]}...)"
    return False, f"sai checksum (sha256={actual_sha[:12]}, md5={actual_md5[:12]})"


def verify_florence_dir(target_dir: Path) -> tuple[bool, str]:
    if not target_dir.is_dir():
        return False, "chưa tồn tại"
    has_cfg = (target_dir / "config.json").is_file()
    has_pre = (target_dir / "preprocessor_config.json").is_file()
    has_weights = (target_dir / "model.safetensors").is_file() or (
        target_dir / "pytorch_model.bin"
    ).is_file()
    if has_cfg and has_pre and has_weights:
        return True, "đủ tệp weights & config"
    return False, "thiếu config.json / preprocessor_config.json / weights"


def _download_stream(url: str, dest_part: Path) -> None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AI-Watermark-Studio-Setup/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = resp.headers.get("Content-Length")
        total_int = int(total) if total and total.isdigit() else None
        downloaded = 0
        last_pct = -10
        with dest_part.open("wb") as out:
            while chunk := resp.read(1024 * 512):
                out.write(chunk)
                downloaded += len(chunk)
                if total_int:
                    pct = int((downloaded * 100) / total_int)
                    if pct >= last_pct + 10:
                        last_pct = pct
                        mb_done = downloaded / (1024 * 1024)
                        mb_total = total_int / (1024 * 1024)
                        print(f"    -> {pct}% ({mb_done:.1f}/{mb_total:.1f} MB)")


def ensure_lama(
    models_dir: Path,
    entry: dict[str, Any],
    *,
    dry_run: bool = False,
    check_only: bool = False,
    force: bool = False,
) -> bool:
    target = models_dir / entry.get("local_relpath", "big-lama.pt")
    valid, reason = verify_lama_file(target, entry)
    if valid and not force:
        print(f"[LaMa] Đã sẵn sàng tại {target} ({reason}).")
        return True

    if check_only or dry_run:
        mode = "CHECK" if check_only else "DRY-RUN"
        urls = [entry.get("url"), *(entry.get("fallback_urls") or [])]
        print(f"[LaMa][{mode}] Trạng thái: {reason}. Đích: {target}")
        for u in [x for x in urls if x]:
            print(f"    nguồn: {u}")
        return check_only is False

    target.parent.mkdir(parents=True, exist_ok=True)
    part_path = target.with_suffix(".pt.part")
    urls = [u for u in [entry.get("url"), *(entry.get("fallback_urls") or [])] if u]

    last_err: Exception | None = None
    for idx, url in enumerate(urls, start=1):
        print(f"[LaMa] Đang tải từ nguồn {idx}/{len(urls)}: {url}")
        try:
            _download_stream(url, part_path)
            ok, msg = verify_lama_file(part_path, entry)
            if not ok:
                raise RuntimeError(f"Kiểm tra checksum thất bại: {msg}")
            os.replace(part_path, target)
            print(f"[LaMa] Hoàn tất & xác thực thành công: {target} ({msg})")
            return True
        except Exception as exc:
            last_err = exc
            print(f"[LaMa] Nguồn {idx} thất bại: {exc}")
            if part_path.exists():
                part_path.unlink(missing_ok=True)

    raise RuntimeError(f"Không thể tải Big-LaMa từ mọi nguồn dự phòng: {last_err}")


def ensure_florence2(
    models_dir: Path,
    entry: dict[str, Any],
    *,
    dry_run: bool = False,
    check_only: bool = False,
    force: bool = False,
) -> bool:
    repo_id = entry.get("repo_id", "microsoft/Florence-2-base")
    revision = entry.get("revision", "main")
    target_dir = models_dir / entry.get("local_relpath", "florence2-base")

    valid, reason = verify_florence_dir(target_dir)
    if valid and not force:
        print(f"[Florence-2] Đã sẵn sàng tại {target_dir} ({reason}).")
        return True

    if check_only or dry_run:
        mode = "CHECK" if check_only else "DRY-RUN"
        print(
            f"[Florence-2][{mode}] Trạng thái: {reason}. Repo: {repo_id}@{revision} -> {target_dir}"
        )
        return check_only is False

    from huggingface_hub import HfApi, snapshot_download  # type: ignore[import-untyped]

    ignore_patterns = ["*.msgpack", "*.h5", "*.ot", "onnx/*", "*.onnx"]
    try:
        files = HfApi().list_repo_files(repo_id=repo_id, revision=revision)
        has_safetensors = any(f.endswith("model.safetensors") for f in files)
        if has_safetensors and importlib.util.find_spec("safetensors") is not None:
            ignore_patterns.append("pytorch_model.bin")
    except Exception:
        pass

    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"[Florence-2] Đang tải snapshot {repo_id}@{revision} -> {target_dir}")
    snapshot_download(
        repo_id=repo_id,
        revision=revision,
        local_dir=str(target_dir),
        ignore_patterns=ignore_patterns,
        force_download=force,
    )
    ok, msg = verify_florence_dir(target_dir)
    if not ok:
        raise RuntimeError(f"Florence-2 tải xong nhưng không hợp lệ: {msg}")
    print(f"[Florence-2] Hoàn tất tại {target_dir} ({msg}).")
    return True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tải và xác thực trọng số AI cục bộ cho AI Watermark Studio."
    )
    parser.add_argument(
        "--only",
        choices=["all", "lama", "florence2"],
        default="all",
        help="Chỉ định model cần kiểm tra/tải (mặc định: all).",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=DEFAULT_MODELS_DIR,
        help="Thư mục lưu trọng số (mặc định: backend/models).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Đường dẫn manifest.json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ hiển thị kế hoạch tải, không ghi mạng/đĩa.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Kiểm tra sự tồn tại và toàn vẹn weights hiện có; thoát mã 1 nếu thiếu.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Tải lại dù trọng số đã tồn tại.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    models = load_manifest(args.manifest)
    ok = True

    if args.only in ("all", "lama") and "lama" in models:
        res = ensure_lama(
            args.models_dir,
            models["lama"],
            dry_run=args.dry_run,
            check_only=args.check,
            force=args.force,
        )
        ok = ok and res

    if args.only in ("all", "florence2") and "florence2" in models:
        res = ensure_florence2(
            args.models_dir,
            models["florence2"],
            dry_run=args.dry_run,
            check_only=args.check,
            force=args.force,
        )
        ok = ok and res

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
