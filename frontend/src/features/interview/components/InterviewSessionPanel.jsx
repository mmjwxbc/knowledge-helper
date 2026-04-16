import { memo } from 'react';
import { Button, Input, Space } from 'antd';
import { CloseOutlined, ExperimentOutlined, SendOutlined } from '@ant-design/icons';
import EmptyState from '../../../components/ui/EmptyState';
import SectionIntro from '../../../components/ui/SectionIntro';
import StatusPill from '../../../components/ui/StatusPill';
import { cx } from '../../../lib/classNames';
import InterviewConversation from './InterviewConversation';
import InterviewQuestionList from './InterviewQuestionList';

const { TextArea } = Input;

function InterviewSessionPanel({
  session,
  sessions,
  messages,
  input,
  loading,
  onInputChange,
  onOpenAnalyzer,
  onOpenSession,
  onSend,
  onClose,
  scrollRef,
}) {
  if (!session) {
    return (
      <div className="main-stack">
        <EmptyState
          icon={<ExperimentOutlined />}
          title="未找到面试会话"
          description="返回分析页重新选择一个项目，或者先创建新的分析任务。"
        />
      </div>
    );
  }

  return (
    <div className="main-stack">
      <SectionIntro
        eyebrow="Interview Session"
        title={session.analysis?.project_name || '面试会话'}
        description={session.analysis?.summary || '已经生成项目摘要和候选问题，可以继续模拟追问。'}
        aside={<StatusPill tone="success">{session.questions?.length || 0} 个问题</StatusPill>}
      />

      <div className="interview-layout">
        <div className="main-stack">
          <div className="surface-card interview-panel">
            <div className="interview-panel-head">
              <div>
                <div className="surface-emphasis">项目摘要</div>
                <p className="muted-text">
                  {session.analysis?.language || '未知语言'}
                  {session.code_url ? ` · ${session.code_url}` : ''}
                </p>
              </div>
              <Space wrap>
                <Button size="small" onClick={onOpenAnalyzer}>
                  分析新代码
                </Button>
                <Button size="small" type="text" icon={<CloseOutlined />} onClick={onClose}>
                  关闭
                </Button>
              </Space>
            </div>

            {session.analysis?.tech_stack?.length ? (
              <div className="review-block">
                <div className="surface-label">技术栈</div>
                <div className="tag-row">
                  {session.analysis.tech_stack.map((tech) => (
                    <StatusPill key={tech}>{tech}</StatusPill>
                  ))}
                </div>
              </div>
            ) : null}

            {session.analysis?.key_modules?.length ? (
              <div className="review-block">
                <div className="surface-label">关键模块</div>
                <div className="interview-module-list">
                  {session.analysis.key_modules.map((moduleName) => (
                    <div key={moduleName} className="interview-module-item">
                      {moduleName}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          <InterviewQuestionList questions={session.questions} />

          <div className="surface-card interview-panel">
            <div>
              <div className="surface-emphasis">追问交流</div>
              <p className="muted-text">围绕项目代码、设计取舍和问题提示继续追问，响应会流式展开。</p>
            </div>

            <InterviewConversation messages={messages} loading={loading} scrollRef={scrollRef} />

            <div className="chat-input-wrap interview-input-wrap">
              <TextArea
                value={input}
                onChange={(event) => onInputChange(event.target.value)}
                placeholder="例如：如果把这个项目部署到生产环境，最先会补哪些治理能力？"
                autoSize={{ minRows: 1, maxRows: 5 }}
                className="chat-composer-input"
                onPressEnter={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    onSend();
                  }
                }}
              />
              <Button
                type="primary"
                shape="circle"
                icon={<SendOutlined />}
                onClick={onSend}
                loading={loading}
                disabled={loading || !input.trim()}
                className="chat-send-button"
              />
            </div>
          </div>
        </div>

        <div className="surface-card interview-panel interview-history-panel">
          <div>
            <div className="surface-emphasis">切换会话</div>
            <p className="muted-text">面试分析结果会保留在列表里，可以直接切换项目继续追问。</p>
          </div>

          <div className="interview-session-list">
            {sessions.map((sessionItem) => (
              <button
                key={sessionItem.session_id}
                type="button"
                className={cx(
                  'interview-session-card',
                  sessionItem.session_id === session.session_id && 'interview-session-card-active',
                )}
                onClick={() => onOpenSession(sessionItem)}
              >
                <div className="interview-session-card-head">
                  <strong>{sessionItem.analysis?.project_name || '未命名项目'}</strong>
                  <StatusPill tone="neutral">{sessionItem.questions?.length || 0} 题</StatusPill>
                </div>
                <div className="muted-text">
                  {sessionItem.analysis?.language || '未知语言'}
                  {sessionItem.created_at
                    ? ` · ${new Date(sessionItem.created_at).toLocaleString('zh-CN')}`
                    : ''}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default memo(InterviewSessionPanel);
