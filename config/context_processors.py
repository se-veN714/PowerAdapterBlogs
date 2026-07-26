"""公开站点元数据的模板上下文。"""

from PowerAdapterBlogs.public_urls import public_absolute_url


def public_site_metadata(request):
    return {
        "site_canonical_url": public_absolute_url(request.path),
        "site_default_description": "PowerAdapter 的个人博客：自动化、加密、算法与精神节律。",
        "site_default_og_image": public_absolute_url(
            "/static/img/PowerAdapter_logo.webp"
        ),
    }
