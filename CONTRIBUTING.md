# 协作与 Git 规范

## 分支与提交流程

- **主分支 `main`**：受保护，不接受直接 push，仅通过合并 PR 更新。
- **开发分支 `develop`**：日常开发与首次代码入库在此分支。
- **功能分支**：新功能从 `develop` 拉取，命名建议 `feature/xxx` 或 `fix/xxx`。

## 推荐流程

1. 从 `develop` 拉取最新：`git checkout develop && git pull origin develop`
2. 新建功能分支：`git checkout -b feature/your-feature`
3. 开发、提交：`git add . && git commit -m "feat: 描述"`
4. 推送到远端：`git push -u origin feature/your-feature`
5. 在 GitHub 上创建 **Pull Request**：`feature/your-feature` → `develop`（或合并到 `main` 的 PR：`develop` → `main`）
6. 代码评审通过后合并，不直接 push 到 `main`。

## 首次入库说明

当前仓库首次代码已推送到 **`develop`** 分支。  
将 `develop` 合并到 `main` 请：

1. 在 GitHub 打开仓库 [lumist_examAgent_backend](https://github.com/lazy233/lumist_examAgent_backend)
2. 创建 **Pull Request**：base 选 `main`，compare 选 `develop`
3. 合并后可在 **Settings → Branches** 中为 `main` 设置分支保护（禁止直接 push，要求 PR）

## Commit 信息建议

- `feat: 新功能`
- `fix: 修复问题`
- `chore: 构建/脚本/依赖等`
- `docs: 文档`
