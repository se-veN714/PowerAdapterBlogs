"""只发布公开正式文章的 RSS 与 Atom Feed。"""

from django.contrib.syndication.views import Feed
from django.urls import reverse
from django.utils.feedgenerator import Atom1Feed

from Blogs.models import Post
from PowerAdapterBlogs.public_urls import public_absolute_url


class PublicPostFeed(Feed):
    title = "PowerAdapter Blogs"
    description = "PowerAdapter Blogs 的公开文章更新"

    def link(self):
        return public_absolute_url(reverse("Blogs:post_list"))

    def items(self):
        return (
            Post.publicly_visible_posts()
            .select_related("owner", "category")
            .order_by("-created_time", "-pk")[:20]
        )

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        return item.desc

    def item_link(self, item):
        return public_absolute_url(item.get_absolute_url())

    def item_pubdate(self, item):
        return item.created_time

    def item_updateddate(self, item):
        return item.update_time

    def item_author_name(self, item):
        return item.owner.username


class PublicPostAtomFeed(PublicPostFeed):
    feed_type = Atom1Feed
    subtitle = PublicPostFeed.description
