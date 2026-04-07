# raw/log/

cc-lead intent=log dispatch 的落盘目录，以及通用任务文档。

cc-lead 每次发送 intent=log dispatch 给 wiki-curator 时，
wiki-curator 会先把 content 落盘到这里，再蒸馏进 wiki 对应章节。

格式：`{timestamp}-{category}-{slug}.md`
Category: decision | bug | status | architecture | agent | conflict
