import { startTransition, useCallback, useEffect, useRef, useState } from 'react';
import { message } from 'antd';
import { API_BASE } from '../../../lib/api';
import { createInterviewMessageId } from '../constants';
import { readSseStream } from '../lib/sse';

const buildInterviewAskUrl = (sessionId) =>
  `${API_BASE}/interview/ask?session_id=${encodeURIComponent(sessionId)}`;

const normalizeInterviewMessage = (messageItem, index) => ({
  id:
    messageItem.id ||
    `${messageItem.type || messageItem.role || 'interview_message'}_${index}_${messageItem.created_at || 'local'}`,
  type: messageItem.type || (messageItem.role === 'assistant' ? 'assistant' : 'user'),
  content: messageItem.content || '',
  created_at: messageItem.created_at,
});

const normalizeInterviewMessages = (messages) =>
  (messages || []).map((messageItem, index) => normalizeInterviewMessage(messageItem, index));

export default function useInterviewAssistant({ selectedChatCategory, selectedChatTags }) {
  const [interviewMode, setInterviewMode] = useState(null);
  const [interviewSessions, setInterviewSessions] = useState([]);
  const [currentInterviewSession, setCurrentInterviewSession] = useState(null);
  const [currentInterviewSessionId, setCurrentInterviewSessionId] = useState('');
  const [interviewCodeUrl, setInterviewCodeUrl] = useState('');
  const [interviewCodeFile, setInterviewCodeFile] = useState(null);
  const [interviewDifficulty, setInterviewDifficulty] = useState('medium');
  const [interviewQuestionCount, setInterviewQuestionCount] = useState(10);
  const [interviewProgress, setInterviewProgress] = useState(0);
  const [interviewProgressMessage, setInterviewProgressMessage] = useState('');
  const [interviewMessages, setInterviewMessages] = useState([]);
  const [interviewInput, setInterviewInput] = useState('');
  const [interviewLoading, setInterviewLoading] = useState(false);
  const interviewMessagesEndRef = useRef(null);

  const fetchInterviewSessions = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/interview/sessions`);
      if (!response.ok) throw new Error('会话列表加载失败');
      const data = await response.json();
      startTransition(() => {
        setInterviewSessions(data.sessions || []);
      });
    } catch (error) {
      console.error('Failed to fetch interview sessions:', error);
    }
  }, []);

  const loadInterviewSessionDetail = useCallback(async (sessionId) => {
    const response = await fetch(`${API_BASE}/interview/session/${encodeURIComponent(sessionId)}`);
    if (!response.ok) {
      throw new Error('面试会话加载失败');
    }
    return response.json();
  }, []);

  useEffect(() => {
    fetchInterviewSessions();
  }, [fetchInterviewSessions]);

  useEffect(() => {
    interviewMessagesEndRef.current?.scrollIntoView({ block: 'end' });
  }, [interviewMessages, interviewLoading]);

  const openInterviewAnalyzer = useCallback(() => {
    setInterviewMode('analyze');
  }, []);

  const closeInterview = useCallback(() => {
    setInterviewMode(null);
    setCurrentInterviewSessionId('');
  }, []);

  const openInterviewSession = useCallback(async (session) => {
    if (!session?.session_id) {
      message.error('面试会话不存在');
      return;
    }

    try {
      const sessionDetail = await loadInterviewSessionDetail(session.session_id);
      setCurrentInterviewSession(sessionDetail);
      setCurrentInterviewSessionId(sessionDetail.session_id || session.session_id);
      setInterviewMessages(normalizeInterviewMessages(sessionDetail.messages));
      setInterviewInput('');
      setInterviewProgress(0);
      setInterviewProgressMessage('');
      setInterviewMode('session');
    } catch (error) {
      console.error('Failed to open interview session:', error);
      message.error(error.message || '面试会话加载失败');
    }
  }, [loadInterviewSessionDetail]);

  const analyzeInterviewCode = useCallback(async () => {
    if (!interviewCodeUrl.trim() && !interviewCodeFile) {
      message.error('请提供代码 URL 或上传压缩文件');
      return;
    }

    setInterviewProgress(0);
    setInterviewProgressMessage('开始分析代码...');
    setInterviewLoading(true);

    try {
      const formData = new FormData();
      if (interviewCodeUrl.trim()) {
        formData.append('code_url', interviewCodeUrl.trim());
      }
      if (interviewCodeFile) {
        formData.append('file', interviewCodeFile);
      }
      formData.append('difficulty', interviewDifficulty);
      formData.append('question_count', String(interviewQuestionCount));

      const response = await fetch(`${API_BASE}/interview/analyze`, {
        method: 'POST',
        body: formData,
      });
      if (!response.ok) throw new Error('分析请求失败');

      await readSseStream(response, async (data) => {
        if (data.status === 'processing') {
          setInterviewProgress(data.progress || 0);
          setInterviewProgressMessage(data.message || '');
          return;
        }

        if (data.status === 'completed' && data.result) {
          setCurrentInterviewSession(data.result);
          setCurrentInterviewSessionId(data.result.session_id || '');
          setInterviewMessages(normalizeInterviewMessages(data.result.messages));
          setInterviewInput('');
          setInterviewMode('session');
          message.success('代码分析完成');
          return;
        }

        if (data.status === 'error') {
          throw new Error(data.message || '代码分析失败');
        }
      });

      await fetchInterviewSessions();
    } catch (error) {
      console.error('Failed to analyze interview code:', error);
      message.error(error.message || '代码分析失败');
    } finally {
      setInterviewLoading(false);
    }
  }, [
    fetchInterviewSessions,
    interviewCodeFile,
    interviewCodeUrl,
    interviewDifficulty,
    interviewQuestionCount,
  ]);

  const sendInterviewMessage = useCallback(async () => {
    const nextQuestion = interviewInput.trim();
    const resolvedSessionId = currentInterviewSession?.session_id || currentInterviewSessionId;

    if (!nextQuestion || !resolvedSessionId) {
      if (!resolvedSessionId) {
        message.error('当前面试会话无效，请重新打开会话');
      }
      return;
    }

    const userMessage = {
      id: createInterviewMessageId('interview_user'),
      type: 'user',
      content: nextQuestion,
    };
    const assistantMessageId = createInterviewMessageId('interview_assistant');

    setInterviewMessages((prev) => [
      ...prev,
      userMessage,
      { id: assistantMessageId, type: 'assistant', content: '' },
    ]);
    setInterviewInput('');
    setInterviewLoading(true);

    try {
      const response = await fetch(buildInterviewAskUrl(resolvedSessionId), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question: nextQuestion,
          category: selectedChatCategory || null,
          tags: selectedChatTags,
        }),
      });
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || '发送问题失败');
      }

      let assistantResponse = '';
      await readSseStream(response, async (data) => {
        if (!data.content) return;
        assistantResponse += data.content;
        setInterviewMessages((prev) =>
          prev.map((messageItem) =>
            messageItem.id === assistantMessageId
              ? { ...messageItem, content: assistantResponse }
              : messageItem,
          ),
        );
      });

      setCurrentInterviewSession((prev) =>
        prev
          ? {
              ...prev,
              messages: [
                ...normalizeInterviewMessages(prev.messages),
                userMessage,
                { id: assistantMessageId, type: 'assistant', content: assistantResponse },
              ],
            }
          : prev,
      );
    } catch (error) {
      console.error('Failed to send interview message:', error);
      message.error(error.message || '发送问题失败');
      setInterviewMessages((prev) =>
        prev.map((messageItem) =>
          messageItem.id === assistantMessageId
            ? { ...messageItem, content: '抱歉，回答问题时出现错误。' }
            : messageItem,
        ),
      );
    } finally {
      setInterviewLoading(false);
    }
  }, [
    currentInterviewSession?.session_id,
    currentInterviewSessionId,
    interviewInput,
    selectedChatCategory,
    selectedChatTags,
  ]);

  return {
    interviewMode,
    interviewSessions,
    currentInterviewSession,
    currentInterviewSessionId,
    interviewCodeUrl,
    setInterviewCodeUrl,
    setInterviewCodeFile,
    interviewDifficulty,
    setInterviewDifficulty,
    interviewQuestionCount,
    setInterviewQuestionCount,
    interviewProgress,
    interviewProgressMessage,
    interviewMessages,
    interviewInput,
    setInterviewInput,
    interviewLoading,
    interviewMessagesEndRef,
    openInterviewAnalyzer,
    openInterviewSession,
    closeInterview,
    analyzeInterviewCode,
    sendInterviewMessage,
  };
}
