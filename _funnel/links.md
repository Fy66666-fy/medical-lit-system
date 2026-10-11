# 渠道投放链接（带来源标记）

**投放时一律用下面这些带 `?f=` 的链接**，不要用裸链接。

带标记后，落地页能识别访客来自哪个渠道，漏斗的 **L1→L2（点击率）才能算出来**。
不带标记的话，所有访问都混在一起，渠道优劣无从判断，前面所有推广都白做。

渠道码用英文是有意的：中文在 URL 里要百分号编码，各平台复制粘贴、自动识别时容易断链。

## 链接清单

| 渠道 | 渠道码 | 投放链接 |
|---|---|---|
| 丁香园 | `dxy` | `https://fy66666-fy.github.io/medical-lit-system/?f=dxy` |
| 知乎 | `zhihu` | `https://fy66666-fy.github.io/medical-lit-system/?f=zhihu` |
| 小木虫 | `xmc` | `https://fy66666-fy.github.io/medical-lit-system/?f=xmc` |
| 小红书 | `xhs` | `https://fy66666-fy.github.io/medical-lit-system/?f=xhs` |
| B站 | `bili` | `https://fy66666-fy.github.io/medical-lit-system/?f=bili` |
| GitHub | `github` | `https://fy66666-fy.github.io/medical-lit-system/?f=github` |
| 直接访问（线下/私聊） | `direct` | `https://fy66666-fy.github.io/medical-lit-system/?f=direct` |

## 各渠道投放位

| 渠道 | 放哪 | 注意 |
|---|---|---|
| **丁香园** | 帖子正文结尾；个人签名档（长期） | 签名档是唯一能持续曝光的位置，优先占住 |
| **知乎** | 回答末尾；文章「参考资料」前 | 硬广有折叠风险，先给方法干货再放链接 |
| **小木虫** | 相关版块求助/资源帖 | 版规严，先混脸熟再发资源 |
| **小红书** | 图文笔记：图片放产品截图，链接放评论区置顶 | **正文放外链大概率被限流**，务必放评论区 |
| **B站** | 视频简介区 + 置顶评论 | 视频内容优先做「三分钟上手」 |
| **GitHub** | README 顶部徽章下 | 面向开发者，转化率通常最高但量小 |

## 使用规则

1. **一个渠道只用自己的码**，不要混用，否则数据全废；
2. 同一渠道多篇内容**用同一个码**（渠道级归因，不做到单篇）；
3. 如果只想看单篇效果，可以后缀再加标记（如 `?f=dxy&p=post01`），
   但 `collect.py` 目前只按渠道汇总，单篇数据需要自己另记；
4. 短链服务（如各平台自带跳转）会**吃掉 query 参数**——投放前先点一次自己的链接，
   确认地址栏里 `?f=` 还在。

## 投放后怎么验证

**1. 客户端**：打开落地页（带上你的渠道参数），按 F12 → Console，会打印一行

```
[funnel] source=dxy
```

**2. 网络**：F12 → Network，应能看到一个到计数服务的请求

```
GET https://medlit-counter.app.workbuddy.host/hit?f=dxy   →  200, image/gif
```

**3. 服务端**：隔几分钟后访问计数服务的统计端点，确认数字在涨

```
https://medlit-counter.app.workbuddy.host/stats?week=2026-W41
→ {"丁香园": 12, ...}
```

三步都对，说明归因链路通了。之后每周用 `collect.py --auto` 把数拉回本地入库即可。
