import { memo } from 'react';
import { Space } from 'antd';
import MarkdownMessage from '../../../components/ui/MarkdownMessage';
import StatusPill from '../../../components/ui/StatusPill';
import {
  INTERVIEW_CATEGORY_LABELS,
  INTERVIEW_DIFFICULTY_OPTIONS,
  getInterviewDifficultyTone,
} from '../constants';

function InterviewQuestionList({ questions }) {
  if (!questions?.length) return null;

  return (
    <div className="surface-card interview-panel">
      <div>
        <div className="surface-emphasis">候选问题</div>
        <p className="muted-text">按问题类型和难度做了归类，便于快速挑题或继续展开。</p>
      </div>

      <div className="interview-question-list">
        {questions.map((question, index) => (
          <article key={`${question.question}-${index}`} className="interview-question-card">
            <div className="interview-question-card-head">
              <div>
                <div className="review-index">问题 {index + 1}</div>
                <div className="review-question">{question.question}</div>
              </div>
              <Space wrap size={8}>
                <StatusPill tone={getInterviewDifficultyTone(question.difficulty)}>
                  {INTERVIEW_DIFFICULTY_OPTIONS.find((option) => option.value === question.difficulty)?.label ||
                    question.difficulty}
                </StatusPill>
                <StatusPill>{INTERVIEW_CATEGORY_LABELS[question.category] || question.category}</StatusPill>
              </Space>
            </div>

            {question.answer_hint ? (
              <div className="answer-block answer-block-markdown">
                <MarkdownMessage content={question.answer_hint} />
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}

export default memo(InterviewQuestionList);
