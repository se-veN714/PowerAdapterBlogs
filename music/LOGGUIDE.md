# Music App — 日志指南

> 配套：[根目录 LOGGUIDE.md](../LOGGUIDE.md)

---

## 状态：空壳

Music app 当前只有模型定义和基础结构，**没有视图、没有路由、没有功能**。V2 也不在其范围内。

---

## 未来启用时的日志点

当 Music app 被激活时，建议在以下位置加日志：

| 操作 | 级别 | 内容 |
|------|------|------|
| 音乐上传 | INFO | filename, size, user_id |
| 音乐删除 | INFO | track_id, title, user_id |
| 播放（如有统计） | — | 不需要，除非做播放量统计且异常时 |
| 上传失败 | ERROR | filename, error |

---

## 当前不需要日志

该 app 目前无任何运行时操作，不需要打任何日志。
