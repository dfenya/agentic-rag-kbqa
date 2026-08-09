/** 品牌/项目配置 —— 所有 UI 文案、图标集中管理，杜绝硬编码 */

export const BRAND = {
  /** 页面标题（浏览器标签页） */
  title: 'Agentic RAG 知识库问答',

  /** 侧边栏品牌名 */
  sidebarName: 'AgenticRAG 知识库问答',

  /** 侧边栏版本号 */
  sidebarVersion: 'Agentic RAG v1 | wudaofen',

  /** 侧边栏 Logo 表情 */
  sidebarLogo: '🤖',

  /** 对话中 AI 助手头像 */
  assistantAvatar: '🤖',

  /** 对话中用户头像 */
  userAvatar: '😎',

  /** 空状态图标 */
  emptyIcon: '🤖',

  /** 聊天页顶部标题 */
  chatHeaderTitle: 'Agentic RAG 知识库问答',

  /** 空状态标题 */
  emptyTitle: 'Agentic RAG 知识库问答',

  /** 空状态描述 */
  emptyDesc: '上传文档构建知识库 · AI 自主检索推理 · 混合检索 + 多 Agent 协作',

  /** 空状态快捷提问 */
  quickQuestions: [
    'Agentic RAG 和普通 RAG 有什么区别？',
    '总结一下上传文档的核心内容',
    '帮我分析几份文档之间的关联',
  ],

  /** 未选知识库时对话区副标题 */
  noKbSubtitle: '就绪 · 未选知识库，走通用 LLM 对话',
  /** 已选知识库时对话区副标题模板：%NAME% 会被替换为知识库名 */
  kbSubtitleTemplate: '知识库：%NAME%（Agentic RAG 模式）',
} as const
