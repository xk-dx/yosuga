# Memory System
Write to memory when:
1. 用户明确要求记住某事（"记住..."、"以后都用..."）
2. 用户纠正了你的行为（说明你之前做错了，应该记住正确的做法）
3. 你发现了可复用的模式（如"这个项目的测试需要先启动数据库"）

**不要**写入：
- 可以从当前代码推断的信息
- 一次性的、不会再用的临时信息
- 已经在 YOSUGA.md 中明确定义的规则

## How to Write Memory

当决定写入记忆时：
1. 在 MEMORY.md 末尾追加一行索引：`- [文件名.md](文件名.md) -- 简短描述（<150字符）`
2. 创建对应的详情文件，写入简短的完整内容
3. 分类选择：user/feedback/project/reference 之一

## How to Read Memory
1. 不要list_dir记忆目录，优先从MEMORY.md 索引里面读取记忆摘要。
2. 有可能存在过期信息以实际项目结构为准。


记忆系统存放在项目文件的.memory_yosuga里面哦