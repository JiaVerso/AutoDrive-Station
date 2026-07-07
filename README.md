🛠️ 开发与 Git 分支管理规范

欢迎加入 AutoDrive-Station 的开发！为了保证代码的安全性和团队协作的极速推进，本仓库实行严格的分支管理与 Code Review (代码审查) 机制。请所有成员在开发前务必阅读并遵循以下 Git 工作流。

1. 分支定义与作用

main 分支：主干分支。只保存绝对稳定、经过测试、可随时发布运行的代码。任何人不得直接推送到此分支。

dev 分支：开发集成分支。包含最新的开发进度，所有人共同维护的核心开发基准。任何人不得直接推送到此分支，必须通过 PR (Pull Request) 合并。

个人/功能分支 (<name>_dev 或 feat/xxx)：日常写代码的地方。以开发者名字（如 xxx_dev）或具体功能命名，必须基于最新的 dev 分支拉取。

2. 标准协同开发流程 (Step-by-Step)

Step 1: 准备开发环境 (每天开发前的第一步)

在开始写新代码前，必须确保你的本地 dev 分支是最新版本，以防止后期的代码冲突。

# 切换到开发分支
git checkout dev

# 从远程仓库拉取最新的 dev 代码
git pull origin dev


Step 2: 创建并切换到个人专属分支

切记：永远不要在 dev 分支上直接写代码！
基于刚才更新好的 dev 分支，创建你自己的分支（例如 xxx_dev 或具体的功能名 feat/ui_update）：

# 创建并自动切换到你的个人分支
git checkout -b xxx_dev


Step 3: 在个人分支上开发并提交

在 jia_dev 分支上愉快地写代码。写完一个阶段性功能后，将修改提交到本地：

# 暂存所有修改
git add .

# 提交并附带清晰的说明（参考下方的 Commit 规范）
git commit -m "feat: 新增 ArUco 视觉跟随控制模块"


Step 4: 同步最新代码 (防冲突神器 ⭐️)

在你写代码的这几个小时里，其他成员可能已经合并了新代码到 dev。在推送到云端前，必须先拉取最新的 dev 代码合并到你的个人分支，在本地解决掉可能存在的冲突：

# 拉取远程最新 dev 分支，并将其合并到你当前的个人分支
git pull origin dev
# (如果提示有冲突，请在编辑器中手动解决冲突后，重新 add 并 commit)


Step 5: 推送个人分支到 GitHub

确保本地没有冲突后，将你的个人分支推送到远程仓库：

git push origin xxx_dev


Step 6: 提交 Pull Request (PR) 与 Code Review

登录 GitHub 仓库主页。

页面会提示你刚刚推送了 xxx_dev，点击绿色的 Compare & pull request 按钮。

确保合并方向是：xxx_dev ➡️ dev。

填写 PR 说明（完成了什么功能，修复了什么 Bug）。

在右侧 Assignees 选择你自己，并在 Reviewers 中选择其他团队成员。

等待至少一名成员 Review 通过后，点击 Merge pull request 合并到 dev。

(合并完成后，你可以选择删除远程的 xxx_dev 分支，下次开发重新从 dev 检出，或者保留该分支继续提交。)

3. 📝 Commit 提交规范建议

为了方便回溯代码历史，我们在 git commit -m 时推荐使用以下前缀标识：

feat: 新增了一个功能 (Feature)

fix: 修复了一个 Bug

docs: 只修改了文档 (README 等)

style: 调整了代码格式、UI 样式 (不影响核心逻辑)

refactor: 代码重构 (既不是新增功能，也不是修复 Bug)

test: 增加或修改测试用例
