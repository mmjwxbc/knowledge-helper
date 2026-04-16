import { memo } from 'react';
import { Button, Input, Progress, Select } from 'antd';
import { CloseOutlined, ExperimentOutlined } from '@ant-design/icons';
import EmptyState from '../../../components/ui/EmptyState';
import SectionIntro from '../../../components/ui/SectionIntro';
import StatusPill from '../../../components/ui/StatusPill';
import { INTERVIEW_DIFFICULTY_OPTIONS } from '../constants';

function InterviewAnalyzePanel({
  codeUrl,
  onCodeUrlChange,
  onFileChange,
  difficulty,
  onDifficultyChange,
  questionCount,
  onQuestionCountChange,
  loading,
  progress,
  progressMessage,
  sessions,
  onOpenSession,
  onAnalyze,
  onClose,
}) {
  return (
    <div className="main-stack">
      <SectionIntro
        eyebrow="Interview Assistant"
        title="针对真实项目，先做代码面试拆解。"
        description="输入仓库地址或上传压缩包，先生成项目摘要和候选问题，再进入追问环节。"
        aside={<StatusPill tone={loading ? 'info' : 'neutral'}>{loading ? '分析中' : '待分析'}</StatusPill>}
      />

      <div className="interview-layout">
        <div className="surface-card interview-panel">
          <div className="interview-panel-head">
            <div>
              <div className="surface-emphasis">代码来源</div>
              <p className="muted-text">支持 GitHub、GitLab 仓库地址，也支持上传 zip 压缩包。</p>
            </div>
            <Button type="text" icon={<CloseOutlined />} onClick={onClose}>
              关闭
            </Button>
          </div>

          <div className="field-group">
            <label>仓库地址</label>
            <Input
              placeholder="https://github.com/user/repo"
              value={codeUrl}
              onChange={(event) => onCodeUrlChange(event.target.value)}
              size="large"
            />
          </div>

          <div className="field-group">
            <label>压缩文件</label>
            <Input
              type="file"
              accept=".zip,.tar,.gz,.tgz"
              onChange={(event) => onFileChange(event.target.files?.[0] || null)}
              size="large"
            />
          </div>

          <div className="interview-config-grid">
            <div className="field-group">
              <label>难度等级</label>
              <Select
                value={difficulty}
                onChange={onDifficultyChange}
                options={INTERVIEW_DIFFICULTY_OPTIONS}
              />
            </div>
            <div className="field-group">
              <label>问题数量</label>
              <Input
                type="number"
                min={1}
                max={30}
                value={questionCount}
                onChange={(event) => onQuestionCountChange(Number(event.target.value) || 1)}
              />
            </div>
          </div>

          {loading ? (
            <div className="interview-progress">
              <Progress percent={progress} status="active" strokeColor="#111827" />
              <div className="muted-text">{progressMessage || '正在准备分析结果'}</div>
            </div>
          ) : null}

          <div className="inline-actions">
            <Button
              type="primary"
              size="large"
              onClick={onAnalyze}
              loading={loading}
              className="primary-action"
            >
              {loading ? '分析中...' : '开始分析'}
            </Button>
          </div>
        </div>

        <div className="surface-card interview-panel interview-history-panel">
          <div>
            <div className="surface-emphasis">最近会话</div>
            <p className="muted-text">分析完成后会保留摘要和问题列表，方便回头继续追问。</p>
          </div>

          {sessions.length > 0 ? (
            <div className="interview-session-list">
              {sessions.map((session) => (
                <button
                  key={session.session_id}
                  type="button"
                  className="interview-session-card"
                  onClick={() => onOpenSession(session)}
                >
                  <div className="interview-session-card-head">
                    <strong>{session.analysis?.project_name || '未命名项目'}</strong>
                    <StatusPill tone={session.status === 'completed' ? 'success' : 'info'}>
                      {session.questions?.length || 0} 题
                    </StatusPill>
                  </div>
                  <div className="muted-text">
                    {session.analysis?.summary?.slice(0, 120) || session.code_url || '等待分析完成'}
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              compact
              icon={<ExperimentOutlined />}
              title="还没有历史面试会话"
              description="先分析一个项目，结果会自动出现在这里。"
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default memo(InterviewAnalyzePanel);
