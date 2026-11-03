# 贾静文_C5_repo链接.md

## 仓库地址

**https://github.com/ZayneWenner/localmap-agent**

## 一句话说明

> **输入一句自然语言（"标出西亚斯学院周边至少 6 个地点"），输出一张可交互的 HTML 地图。**
> 全程跑在本地 Gemma 4 上，不需要 API Key，不需要联网推理，不需要付费。

## 群里分享用的一句话

> 这是我的 C5 GitHub repo：https://github.com/ZayneWenner/localmap-agent
> —— 输入一句话就能得到一张交互式地图，模型跑在本机不上云，欢迎 star、fork、提 Issue！

---

## 仓库内容概览

| 项目 | 说明 |
|---|---|
| 项目名 | localmap-agent |
| 用户名 | ZayneWenner |
| 主语言 | Python 3.10+ |
| 依赖数量 | 1 个（requests，且已做成可选） |
| 本地模型 | Gemma 4 E2B（Q4_K_M，4.6B，Apache 2.0），通过 Ollama 运行 |
| 开源协议 | MIT |
| 文件数 | 29 |
| commit 数 | 4（core → tests → docs → ci/examples，分主题提交） |
| 测试 | 33 个，零第三方依赖，不需要模型和联网 |

## 必须项自查（对照 CHALLENGE.md 第十一节）

```
[x] Repo 是 public（推送后设为 public）
[x] README.md 包含：一句话说明、安装步骤、使用示例、项目结构
[x] 别人 clone 后 5 分钟内能跑起来
      · pip install -r requirements.txt → ollama pull → python run.py --probe
      · 不装任何东西也能跑：python -m unittest discover -s tests -v
[x] 有 LICENSE 文件（MIT）
[x] 有 .gitignore（已排除 __pycache__ / logs / map.html；examples 下的示例文件用根锚定保留）
[x] 有 AI_LOG.md（AI 使用日志，含 v1–v5 五次迭代、四次失败）
[x] 有 ATTRIBUTION.md（拿来说明）
[x] 至少有一个真实的使用示例（examples/ 下放真实 v5 输出 + v1 失败日志）
[x] 群内分享用的一句话说明已备好（见上方「群里分享用的一句话」）
```

## 加分项

| 项 | 状态 |
|---|---|
| CI/CD（GitHub Actions） | ✅ 配置随仓库提供，位于 `ci/github-actions-ci.yml`：Python 3.10–3.13 跑测试 + 导入冒烟 + CLI 检查；复制到 `.github/workflows/` 即启用 |
| CHANGELOG.md | ✅ 含 Unreleased / 1.1.0 / 1.0.0 |
| CONTRIBUTING.md | ✅ 含开发环境、代码风格、commit 规范、PR 流程 |
| Issue 模板 | ✅ bug_report.yml + feature_request.yml |
| PR 模板 | ✅ 含"改了 agent 循环必须填 before/after 表格"的要求 |
| 示例 / Demo | ✅ examples/ 下真实输入输出 |

## 当前状态

- **已发布到 GitHub**：https://github.com/ZayneWenner/localmap-agent
- 仓库为 **public**，默认分支 `main`
- **29 个文件、4 次提交**（core → tests → docs → ci/examples，按主题拆分，便于对照每步改了什么）
- 33 个单元测试已在本机实跑通过（`Ran 33 tests in 0.017s` / `OK`，stdlib unittest，零第三方依赖）
- `python run.py --help` 实测可运行（在无 requests 的环境下也不崩）
- CI 工作流配置文件位于 `ci/github-actions-ci.yml`；受发布令牌权限限制未放入 `.github/workflows/`，因此 Actions 尚未启用，复制过去即可运行

## 发布方式（已完成，供复现参考）

本次通过 GitHub REST API 分四次提交推送：先建仓库，再按 core / tests / docs / ci+examples 四组分别建 tree 与 commit，最后更新 `main` 引用。

若在本地用命令行复现，等价做法是：

```bash
cd "贾静文_C5_提交包/localmap-agent"
git remote add origin https://github.com/ZayneWenner/localmap-agent.git
git push -u origin main
```

> 注意：用 GitHub 网页拖拽上传只会产生一次 commit，看不到这 4 次分主题提交的历史。
