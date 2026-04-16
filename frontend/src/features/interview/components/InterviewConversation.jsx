import { memo } from 'react';
import { Spin, Typography } from 'antd';
import {
  LoadingOutlined,
  MessageOutlined,
  QuestionCircleOutlined,
  UserOutlined,
} from '@ant-design/icons';
import EmptyState from '../../../components/ui/EmptyState';
import MarkdownMessage from '../../../components/ui/MarkdownMessage';
import { cx } from '../../../lib/classNames';

function InterviewConversation({ messages, loading, scrollRef }) {
  return (
    <div className="interview-conversation">
      {messages.length === 0 ? (
        <EmptyState
          compact
          icon={<MessageOutlined />}
          title="开始模拟问答"
          description="可以围绕某一道题、具体模块、设计取舍或优化方案继续追问。"
        />
      ) : (
        messages.map((messageItem, index) => {
          const messageType =
            messageItem.type || (messageItem.role === 'assistant' ? 'assistant' : 'user');
          return (
          <div
            key={messageItem.id || `${messageType}_${index}`}
            className={cx(
              'chat-row',
              'interview-chat-row',
              messageType === 'user' ? 'chat-row-user' : 'chat-row-ai',
            )}
          >
            {messageType === 'assistant' ? <QuestionCircleOutlined className="chat-avatar" /> : null}
            <div
              className={cx(
                'chat-bubble',
                'interview-chat-bubble',
                messageType === 'user' && 'chat-bubble-user',
              )}
            >
              {messageType === 'assistant' ? (
                <MarkdownMessage content={messageItem.content} />
              ) : (
                <Typography.Text>{messageItem.content}</Typography.Text>
              )}
            </div>
            {messageType === 'user' ? <UserOutlined className="chat-avatar" /> : null}
          </div>
          );
        })
      )}

      {loading ? (
        <div className="loading-inline interview-inline-loading">
          <Spin size="small" indicator={<LoadingOutlined spin />} />
          <span>面试助手正在整理回答...</span>
        </div>
      ) : null}

      <div ref={scrollRef} />
    </div>
  );
}

export default memo(InterviewConversation);
