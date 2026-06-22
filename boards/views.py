"""Boards 应用的视图和上下文处理器。

将活跃的首页板块数据注入所有模板上下文，供 base.html / index.html 使用。
"""

from boards.models import Board


def boards_context(request):
    """上下文处理器：注入活跃的首页板块列表。

    按 sort_order 排序，仅供首页 editorial-section 遍历渲染。
    返回 board 对象，模板可通过 board.glitch_color 等属性使用。
    """
    boards = (
        Board.objects.filter(is_active=True)
        .select_related('category')
        .order_by('sort_order')
    )
    return {'boards': boards}
