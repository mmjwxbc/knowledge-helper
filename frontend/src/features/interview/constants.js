export const INTERVIEW_DIFFICULTY_OPTIONS = [
  { label: '简单', value: 'easy' },
  { label: '中等', value: 'medium' },
  { label: '困难', value: 'hard' },
];

export const INTERVIEW_CATEGORY_LABELS = {
  code_understanding: '代码理解',
  optimization: '优化改进',
  design: '设计思路',
  architecture: '架构设计',
  extension: '功能扩展',
};

export const createInterviewMessageId = (prefix) =>
  `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

export const getInterviewDifficultyTone = (difficulty) => {
  if (difficulty === 'easy') return 'success';
  if (difficulty === 'hard') return 'danger';
  return 'info';
};
