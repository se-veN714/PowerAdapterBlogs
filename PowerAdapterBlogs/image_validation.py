"""跨应用复用的图片上传安全校验。"""

from pathlib import Path

from django.core.exceptions import ValidationError
from django.db.models.fields.files import FieldFile
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
ALLOWED_IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "GIF": ("image/gif", ".gif"),
    "WEBP": ("image/webp", ".webp"),
}


def validate_uploaded_image(uploaded_file):
    """验证大小、MIME、真实格式和像素数量，返回安全扩展名。"""
    # ModelForm 在未替换图片时仍会对数据库中的 FieldFile 执行模型校验。
    # 该文件已在首次上传时完成内容校验，且不具备 UploadedFile.content_type。
    if isinstance(uploaded_file, FieldFile):
        return Path(uploaded_file.name).suffix.lower()

    if uploaded_file.size > MAX_IMAGE_SIZE:
        raise ValidationError("图片不能超过 5MB。")

    declared_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    allowed_mimes = {item[0] for item in ALLOWED_IMAGE_FORMATS.values()}
    if declared_type not in allowed_mimes:
        raise ValidationError("仅支持 JPEG、PNG、GIF 或 WEBP 图片。")

    try:
        image = Image.open(uploaded_file)
        image_format = (image.format or "").upper()
        width, height = image.size
        image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValidationError("上传文件不是有效图片。") from exc
    finally:
        uploaded_file.seek(0)

    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError("图片编码格式不受支持。")
    expected_mime, safe_extension = ALLOWED_IMAGE_FORMATS[image_format]
    if declared_type != expected_mime:
        raise ValidationError("图片 MIME 类型与实际内容不一致。")
    if width * height > MAX_IMAGE_PIXELS:
        raise ValidationError("图片像素总量不能超过 2500 万。")

    original_extension = Path(uploaded_file.name).suffix.lower()
    allowed_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    if original_extension and original_extension not in allowed_extensions:
        raise ValidationError("图片文件扩展名不受支持。")
    return safe_extension
