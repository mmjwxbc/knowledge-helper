import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Form,
  Input,
  Layout,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Spin,
  Typography,
  message,
} from 'antd';
import {
  CheckCircleOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
  LoadingOutlined,
  MessageOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  SendOutlined,
  UserOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './App.css';

const { Sider, Content } = Layout;
const { TextArea } = Input;

const API_BASE = 'http://localhost:8000/api';

const generateChatConversationId = () =>
  `chat_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

const buildConversationTitle = (messages) => {
  const firstUserMessage = (messages || []).find(
    (msg) => msg.type === 'user' && msg.content?.trim(),
  );
  if (!firstUserMessage) return '新对话';
  return firstUserMessage.content.trim().slice(0, 30) || '新对话';
};

const normalizeTagList = (tags) =>
  Array.from(
    new Set(
      (tags || [])
        .map((tag) => (typeof tag === 'string' ? tag.trim() : ''))
        .filter(Boolean),
    ),
  );

const cx = (...parts) => parts.filter(Boolean).join(' ');

const STATUS_META = {
  idle: { label: '待开始', tone: 'neutral' },
  processing: { label: '处理中', tone: 'info' },
  reviewing: { label: '待确认', tone: 'warning' },
  categories: { label: '分类视图', tone: 'neutral' },
  knowledgeBase: { label: '知识库', tone: 'success' },
};

const TASK_STATUS_META = {
  pending: '等待中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
};

function StatusPill({ children, tone = 'neutral' }) {
  return <span className={cx('status-pill', `status-pill-${tone}`)}>{children}</span>;
}

function SectionIntro({ eyebrow, title, description, aside }) {
  return (
    <div className="section-intro">
      <div>
        {eyebrow ? <div className="section-eyebrow">{eyebrow}</div> : null}
        <h1 className="section-title">{title}</h1>
        {description ? <p className="section-description">{description}</p> : null}
      </div>
      {aside ? <div className="section-aside">{aside}</div> : null}
    </div>
  );
}

function EmptyState({ icon, title, description, compact = false }) {
  return (
    <div className={cx('empty-state', compact && 'empty-state-compact')}>
      <div className="empty-icon">{icon}</div>
      <div className="empty-title">{title}</div>
      {description ? <p className="empty-description">{description}</p> : null}
    </div>
  );
}

function StatCard({ label, value, hint }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-hint">{hint}</div>
    </div>
  );
}

function App() {
  const [categories, setCategories] = useState([]);
  const [reviewTagOptions, setReviewTagOptions] = useState([]);
  const [currentResult, setCurrentResult] = useState(null);
  const [feedback, setFeedback] = useState('');
  const [finalItems, setFinalItems] = useState([]);
  const [status, setStatus] = useState('idle');
  const [inputMode, setInputMode] = useState('url');
  const [url, setUrl] = useState('');
  const [pastedText, setPastedText] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('');
  const [addCategoryModal, setAddCategoryModal] = useState(false);
  const [selectedItems, setSelectedItems] = useState([]);
  const [form] = Form.useForm();
  const [expandedCards, setExpandedCards] = useState(new Set());
  const [confirmProgress, setConfirmProgress] = useState(0);
  const [confirmStatus, setConfirmStatus] = useState('idle');
  const [taskQueue, setTaskQueue] = useState([]);
  const [currentTaskId, setCurrentTaskId] = useState(null);
  const [extractMode, setExtractMode] = useState('text_and_images');
  const [editedTags, setEditedTags] = useState({});

  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [chatConversations, setChatConversations] = useState([]);
  const [currentChatId, setCurrentChatId] = useState('');
  const [selectedChatCategory, setSelectedChatCategory] = useState('');
  const [selectedChatTags, setSelectedChatTags] = useState([]);
  const [chatTagOptions, setChatTagOptions] = useState([]);
  const [showChatSidebar, setShowChatSidebar] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(380);
  const [isResizing, setIsResizing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');

  const messagesEndRef = useRef(null);
  const sidebarRef = useRef(null);

  useEffect(() => {
    fetchCategories();
    fetchTagsForReview();
  }, []);

  useEffect(() => {
    fetchChatConversations();
  }, []);

  useEffect(() => {
    setEditedTags({});
    setSelectedItems([]);
  }, [currentResult]);

  useEffect(() => {
    fetchTagsForReview(currentResult?.category);
  }, [currentResult?.category]);

  useEffect(() => {
    fetchTagsForChat(selectedChatCategory);
    setSelectedChatTags([]);
  }, [selectedChatCategory]);

  useEffect(() => {
    if (chatMessages.length === 0 || isLoading || !currentChatId) return;
    saveChatConversation(currentChatId, chatMessages, selectedChatCategory, selectedChatTags);
  }, [chatMessages, currentChatId, selectedChatCategory, selectedChatTags, isLoading]);

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!isResizing || !sidebarRef.current) return;
      const sidebarRect = sidebarRef.current.getBoundingClientRect();
      const newWidth = sidebarRect.right - e.clientX;
      if (newWidth > 280 && newWidth < 760) {
        setSidebarWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing]);

  useEffect(() => {
    if (messagesEndRef.current?.scrollTop !== undefined) {
      messagesEndRef.current.scrollTop = messagesEndRef.current.scrollHeight;
    }
  }, [chatMessages]);

  const fetchVaultDataByCategory = async (category = null) => {
    try {
      const targetUrl = category
        ? `${API_BASE}/vault?category=${encodeURIComponent(category)}`
        : `${API_BASE}/vault`;
      const response = await fetch(targetUrl);
      const data = await response.json();
      if (data.items) {
        setFinalItems(data.items);
      }
    } catch (error) {
      console.error('Failed to fetch vault data:', error);
    }
  };

  const fetchCategories = async () => {
    try {
      const response = await fetch(`${API_BASE}/categories`);
      const data = await response.json();
      if (data.categories) {
        setCategories(data.categories);
      }
    } catch (error) {
      console.error('Failed to fetch categories:', error);
    }
  };

  const fetchTagsForReview = async (category = null) => {
    try {
      const targetUrl = category
        ? `${API_BASE}/tags?category=${encodeURIComponent(category)}`
        : `${API_BASE}/tags`;
      const response = await fetch(targetUrl);
      const data = await response.json();
      if (data.tags) {
        setReviewTagOptions(data.tags);
      }
    } catch (error) {
      console.error('Failed to fetch tags:', error);
    }
  };

  const fetchTagsForChat = async (category = null) => {
    try {
      const targetUrl = category
        ? `${API_BASE}/tags?category=${encodeURIComponent(category)}`
        : `${API_BASE}/tags`;
      const response = await fetch(targetUrl);
      const data = await response.json();
      if (data.tags) {
        setChatTagOptions(data.tags);
      }
    } catch (error) {
      console.error('Failed to fetch chat tags:', error);
    }
  };

  const loadChatConversation = useCallback(async (conversationId) => {
    try {
      const response = await fetch(`${API_BASE}/chat/conversations/${conversationId}`);
      if (!response.ok) throw new Error('加载会话失败');
      const data = await response.json();
      setCurrentChatId(data.id);
      setChatMessages(data.messages || []);
      setSelectedChatCategory(data.category || '');
      setSelectedChatTags(data.tags || []);
      setShowChatSidebar(true);
    } catch (error) {
      console.error('Failed to load chat conversation:', error);
      message.error('加载会话失败');
    }
  }, []);

  const fetchChatConversations = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/chat/conversations`);
      const data = await response.json();
      const conversations = data.conversations || [];
      setChatConversations(conversations);

      if (!currentChatId && conversations.length > 0) {
        await loadChatConversation(conversations[0].id);
      }
    } catch (error) {
      console.error('Failed to fetch chat conversations:', error);
    }
  }, [currentChatId, loadChatConversation]);

  const saveChatConversation = async (conversationId, messagesToSave, category = '', tags = []) => {
    if (!conversationId || !messagesToSave || messagesToSave.length === 0) return;
    try {
      const response = await fetch(`${API_BASE}/chat/conversations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: conversationId,
          title: buildConversationTitle(messagesToSave),
          messages: messagesToSave,
          category: category || null,
          tags,
        }),
      });
      const data = await response.json();
      if (data.status === 'success') {
        const listResponse = await fetch(`${API_BASE}/chat/conversations`);
        const listData = await listResponse.json();
        setChatConversations(listData.conversations || []);
      }
    } catch (error) {
      console.error('Failed to save chat conversation:', error);
    }
  };

  const handleNewConversation = () => {
    setCurrentChatId(generateChatConversationId());
    setChatMessages([]);
    setChatInput('');
    setSelectedChatCategory('');
    setSelectedChatTags([]);
    setShowChatSidebar(true);
  };

  const handleDeleteConversation = async (conversationId) => {
    try {
      const response = await fetch(`${API_BASE}/chat/conversations/${conversationId}`, {
        method: 'DELETE',
      });
      const data = await response.json();
      if (!data.success) {
        message.error('删除会话失败');
        return;
      }

      const remainingConversations = chatConversations.filter((item) => item.id !== conversationId);
      setChatConversations(remainingConversations);

      if (currentChatId === conversationId) {
        if (remainingConversations.length > 0) {
          await loadChatConversation(remainingConversations[0].id);
        } else {
          handleNewConversation();
        }
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error);
      message.error('删除会话失败');
    }
  };

  const getCurrentTagsForIndex = (index) => editedTags[index] || currentResult?.tags?.[index] || [];

  const updateEditableTag = (index, tagIndex, value) => {
    const nextTags = [...getCurrentTagsForIndex(index)];
    nextTags[tagIndex] = value;
    setEditedTags((prev) => ({ ...prev, [index]: nextTags }));
  };

  const removeEditableTag = (index, tagIndex) => {
    const nextTags = getCurrentTagsForIndex(index).filter((_, idx) => idx !== tagIndex);
    setEditedTags((prev) => ({ ...prev, [index]: nextTags }));
  };

  const addEditableTag = (index, initialValue = '') => {
    const nextTags = [...getCurrentTagsForIndex(index), initialValue];
    setEditedTags((prev) => ({ ...prev, [index]: nextTags }));
  };

  const applySuggestedTag = (index, tag) => {
    const nextTags = normalizeTagList([...getCurrentTagsForIndex(index), tag]);
    setEditedTags((prev) => ({ ...prev, [index]: nextTags }));
  };

  const knowledgeTagStats = finalItems.reduce((acc, item) => {
    (item.tags || []).forEach((tag) => {
      const cleanTag = typeof tag === 'string' ? tag.trim() : '';
      if (!cleanTag) return;
      acc[cleanTag] = (acc[cleanTag] || 0) + 1;
    });
    return acc;
  }, {});

  const sortedKnowledgeTags = Object.entries(knowledgeTagStats)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'))
    .map(([tag, count]) => ({ tag, count }));

  const fetchVaultData = async () => {
    await fetchVaultDataByCategory();
  };

  const handleDeleteItem = async (itemId) => {
    try {
      const response = await fetch(`${API_BASE}/vault/delete`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: itemId }),
      });
      const data = await response.json();
      if (data.success) {
        message.success('删除成功');
        await fetchVaultDataByCategory(selectedCategory);
      } else {
        message.error('删除失败');
      }
    } catch (error) {
      console.error('删除失败:', error);
      message.error('删除失败，请检查网络连接');
    }
  };

  const generateTaskId = () =>
    Date.now().toString(36) + Math.random().toString(36).slice(2);

  const processNextTask = () => {
    const nextTask = taskQueue.find((task) => task.status === 'pending');
    if (nextTask) {
      setCurrentTaskId(nextTask.id);
      processTask(nextTask);
    } else {
      setCurrentTaskId(null);
    }
  };

  const processTask = async (task) => {
    setTaskQueue((prev) =>
      prev.map((item) => (item.id === task.id ? { ...item, status: 'processing' } : item)),
    );

    setStatus('processing');
    setProgress(0);
    setProgressMessage(task.sourceType === 'text' ? '开始处理文本' : '开始处理 URL');

    try {
      const response = await fetch(`${API_BASE}/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: task.url,
          text: task.text,
          category: task.category || '未分类',
          extract_mode: task.extract_mode || 'text_and_images',
        }),
      });

      if (!response.ok) throw new Error('网络响应错误');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let done = false;
      let timeoutId;

      const timeoutPromise = new Promise((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error('处理超时')), 300000);
      });

      const readPromise = (async () => {
        while (!done) {
          const { value, done: doneReading } = await reader.read();
          done = doneReading;
          const chunk = decoder.decode(value, { stream: true });
          const events = (buffer + chunk).split('\n\n');
          buffer = events.pop() || '';

          for (const event of events) {
            if (!event.startsWith('data:')) continue;
            const dataStr = event.substring(5).trim();
            if (!dataStr || dataStr === '[DONE]') continue;

            try {
              const data = JSON.parse(dataStr);
              if (data.status === 'processing') {
                setProgress(data.progress);
                setProgressMessage(data.message);
                clearTimeout(timeoutId);
                timeoutId = setTimeout(() => {
                  reader.cancel();
                }, 120000);
              } else if (data.status === 'completed') {
                if (data.result.error) {
                  message.error(data.result.error);
                  setTaskQueue((prev) =>
                    prev.map((item) =>
                      item.id === task.id
                        ? { ...item, status: 'failed', error: data.result.error }
                        : item,
                    ),
                  );
                  setStatus('idle');
                } else {
                  setCurrentResult(data.result);
                  setStatus('reviewing');
                  setTaskQueue((prev) =>
                    prev.map((item) =>
                      item.id === task.id
                        ? {
                            ...item,
                            status: 'completed',
                            title:
                              data.result.title ||
                              data.result.preview?.split('\n')[0] ||
                              task.title,
                          }
                        : item,
                    ),
                  );
                }
              } else if (data.status === 'error') {
                message.error(data.message);
                setTaskQueue((prev) =>
                  prev.map((item) =>
                    item.id === task.id ? { ...item, status: 'failed', error: data.message } : item,
                  ),
                );
                setStatus('idle');
              }
            } catch (error) {
              console.error('解析 SSE 数据失败:', error, dataStr);
            }
          }
        }
      })();

      await Promise.race([readPromise, timeoutPromise]);
    } catch (error) {
      message.error(`处理失败: ${error.message}`);
      setTaskQueue((prev) =>
        prev.map((item) =>
          item.id === task.id ? { ...item, status: 'failed', error: error.message } : item,
        ),
      );
      setStatus('idle');
    } finally {
      setTimeout(() => {
        processNextTask();
      }, 500);
    }
  };

  const handleStart = () => {
    const trimmedUrl = url.trim();
    const trimmedText = pastedText.trim();

    if (inputMode === 'url' && !trimmedUrl) {
      message.error('请输入 URL 地址');
      return;
    }

    if (inputMode === 'text' && !trimmedText) {
      message.error('请输入要上传的笔记文本');
      return;
    }

    if (!selectedCategory) {
      message.error('请选择类别');
      return;
    }

    let taskTitle = trimmedUrl;
    if (inputMode === 'url') {
      try {
        const urlObject = new URL(trimmedUrl);
        taskTitle = urlObject.hostname + urlObject.pathname;
      } catch {
        taskTitle = trimmedUrl;
      }
    } else {
      taskTitle = trimmedText.split('\n')[0].slice(0, 40) || '粘贴文本';
    }

    const newTask = {
      id: generateTaskId(),
      sourceType: inputMode,
      url: inputMode === 'url' ? trimmedUrl : '',
      text: inputMode === 'text' ? trimmedText : '',
      category: selectedCategory,
      extract_mode: extractMode,
      title: taskTitle,
      status: 'pending',
      created: new Date().toISOString(),
    };

    setTaskQueue((prev) => [...prev, newTask]);

    if (!currentTaskId) {
      setCurrentTaskId(newTask.id);
      processTask(newTask);
    }

    setUrl('');
    setPastedText('');
    setSelectedCategory('');
  };

  const handleCorrection = async () => {
    if (!currentResult || !feedback) return;

    message.loading('正在根据提示重新处理...', 1);
    try {
      const response = await fetch(`${API_BASE}/process/correct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: currentResult.id, feedback }),
      });

      const data = await response.json();
      if (data.error) {
        message.error(data.error);
      } else {
        setCurrentResult(data);
        setFeedback('');
        message.success('修正完成');
      }
    } catch {
      message.error('修正失败');
    }
  };

  const handleConfirm = async () => {
    if (!currentResult) return;

    try {
      const indicesToSubmit =
        selectedItems.length > 0
          ? selectedItems
          : Array.from({ length: currentResult.questions?.length || 0 }, (_, i) => i);

      if (indicesToSubmit.length === 0) {
        message.error('没有要提交的项目');
        return;
      }

      setConfirmStatus('confirming');
      setConfirmProgress(0);

      let successCount = 0;
      const totalItems = indicesToSubmit.length;

      for (let i = 0; i < indicesToSubmit.length; i += 1) {
        const index = indicesToSubmit[i];
        setConfirmProgress(Math.round((i / totalItems) * 100));

        const response = await fetch(`${API_BASE}/commit`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            id: currentResult.id,
            question: currentResult.questions[index],
            answer: currentResult.answers[index],
            tags: normalizeTagList(editedTags[index] || currentResult.tags[index] || []),
            category: currentResult.category,
          }),
        });

        const data = await response.json();
        if (data.status === 'success') {
          successCount += 1;
        }
      }

      setConfirmProgress(100);

      if (successCount > 0) {
        message.success(`成功入库 ${successCount} 个项目`);
        await fetchVaultData();
        await fetchTagsForReview(currentResult.category);
        await fetchTagsForChat(selectedChatCategory);
        setStatus('idle');
        setCurrentResult(null);
        setSelectedItems([]);
        setEditedTags({});
      } else {
        message.error('入库失败');
      }

      setTimeout(() => {
        setConfirmStatus('idle');
        setConfirmProgress(0);
      }, 1000);
    } catch {
      message.error('入库失败，请检查网络连接');
      setConfirmStatus('idle');
      setConfirmProgress(0);
    }
  };

  const handleAddCategory = async () => {
    try {
      const values = await form.validateFields();
      const response = await fetch(`${API_BASE}/categories`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: values.name }),
      });

      const data = await response.json();
      if (data.status === 'success') {
        message.success('类别添加成功');
        await fetchCategories();
        setAddCategoryModal(false);
        form.resetFields();
      } else {
        message.error(data.message || '添加失败');
      }
    } catch (error) {
      console.error(error);
    }
  };

  const handleSendMessage = async () => {
    const nextInput = chatInput.trim();
    if (!nextInput) return;

    const conversationId = currentChatId || generateChatConversationId();
    if (!currentChatId) {
      setCurrentChatId(conversationId);
    }

    const userMessage = {
      id: Date.now(),
      content: nextInput,
      type: 'user',
    };

    setChatMessages((prev) => [...prev, userMessage]);
    setChatInput('');
    setIsLoading(true);

    try {
      const historyForRequest = chatMessages
        .filter((msg) => !msg.loading)
        .map((msg) => ({ type: msg.type, content: msg.content }));

      const response = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: nextInput,
          referenced_ids: [],
          category: selectedChatCategory || null,
          tags: selectedChatTags,
          history: historyForRequest,
        }),
      });

      if (!response.ok) throw new Error('网络响应错误');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      const aiMessageId = Date.now() + 1;
      let aiMessageContent = '';

      setChatMessages((prev) => [
        ...prev,
        { id: aiMessageId, content: '', type: 'ai', loading: true },
      ]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n\n');

        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          const dataStr = line.substring(5).trim();
          if (!dataStr || dataStr === '[DONE]') continue;

          try {
            const data = JSON.parse(dataStr);
            if (data.content) {
              aiMessageContent += data.content;
              setChatMessages((prev) =>
                prev.map((msg) =>
                  msg.id === aiMessageId
                    ? { ...msg, content: aiMessageContent, loading: false }
                    : msg,
                ),
              );
            }
          } catch (error) {
            console.error('解析 SSE 数据失败:', error);
          }
        }
      }

      const finalMessages = [
        ...chatMessages,
        userMessage,
        { id: aiMessageId, content: aiMessageContent, type: 'ai', loading: false },
      ];
      await saveChatConversation(
        conversationId,
        finalMessages,
        selectedChatCategory,
        selectedChatTags,
      );
    } catch (error) {
      console.error('发送消息失败:', error);
      message.error('发送消息失败，请检查网络连接');
      setChatMessages((prev) => prev.slice(0, -1));
    } finally {
      setIsLoading(false);
    }
  };

  const handleMouseDown = (e) => {
    e.preventDefault();
    setIsResizing(true);
  };

  const selectedCount =
    status === 'reviewing' && currentResult?.questions?.length
      ? selectedItems.length || currentResult.questions.length
      : 0;

  const statusMeta = STATUS_META[status] || STATUS_META.idle;

  const renderIdleContent = () => (
    <div className="main-stack">
      <SectionIntro
        eyebrow="Knowledge Helper"
        title="把采集、整理与问答收进一个更安静的工作台。"
        description="左侧录入素材，中间确认结构化结果，右侧跟踪任务或直接进入知识库对话。整体视觉更轻，但信息密度更高。"
        aside={<StatusPill tone={statusMeta.tone}>{statusMeta.label}</StatusPill>}
      />
      <div className="hero-grid">
        <StatCard label="知识分类" value={categories.length} hint="按主题组织沉淀内容" />
        <StatCard label="待处理任务" value={taskQueue.length} hint="支持排队和状态追踪" />
        <StatCard label="历史会话" value={chatConversations.length} hint="保留带筛选条件的问答上下文" />
      </div>
      <div className="hero-panel">
        <div>
          <div className="hero-panel-label">工作方式</div>
          <div className="hero-panel-title">先采集，再校对，最后沉淀成可问答知识。</div>
          <p className="hero-panel-copy">
            这个界面现在更偏向编辑器感：弱化花哨装饰，强化层级、留白和阅读节奏。
          </p>
        </div>
        <div className="hero-panel-actions">
          <Button type="primary" size="large" onClick={() => setStatus('categories')}>
            浏览知识库
          </Button>
          <Button size="large" onClick={() => setShowChatSidebar((value) => !value)}>
            打开对话助手
          </Button>
        </div>
      </div>
    </div>
  );

  const renderProcessingContent = () => (
    <div className="center-panel-wrap">
      <div className="spot-panel">
        <div className="spot-panel-icon">◌</div>
        <div className="spot-panel-title">
          {confirmStatus === 'confirming' ? '正在确认入库' : '正在整理素材'}
        </div>
        <p className="spot-panel-copy">
          {confirmStatus === 'confirming'
            ? '系统会逐条提交内容，并保留当前分类和标签。'
            : progressMessage || '正在抽取正文、结构化问题与标签。'}
        </p>
        <Progress
          percent={confirmStatus === 'confirming' ? confirmProgress : progress}
          status="active"
          strokeColor={{ '0%': '#1f2937', '100%': '#9ca3af' }}
          trailColor="rgba(15, 23, 42, 0.08)"
        />
      </div>
    </div>
  );

  const renderReviewContent = () => (
    <div className="main-stack">
      <SectionIntro
        eyebrow="Review"
        title="结构化结果预览"
        description={`当前共识别 ${currentResult?.questions?.length || 0} 个候选问题，可逐条修正后入库。`}
        aside={<StatusPill tone="warning">待确认 {selectedCount} 项</StatusPill>}
      />

      <div className="surface-card result-summary">
        <div>
          <div className="surface-label">当前分类</div>
          <div className="surface-emphasis">{currentResult?.category}</div>
        </div>
        <div>
          <div className="surface-label">可复用标签</div>
          <div className="tag-row">
            {reviewTagOptions.length > 0 ? (
              reviewTagOptions.slice(0, 10).map((tag) => <StatusPill key={tag}>{tag}</StatusPill>)
            ) : (
              <span className="muted-text">当前分类还没有历史标签</span>
            )}
          </div>
        </div>
      </div>

      <div className="review-grid">
        {currentResult?.questions?.map((question, index) => (
          <Card key={index} className="review-card" bordered={false}>
            <div className="review-card-header">
              <div>
                <div className="review-index">#{index + 1}</div>
                <div className="review-question">{question}</div>
              </div>
              <label className="select-chip">
                <input
                  type="checkbox"
                  checked={selectedItems.includes(index)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedItems([...selectedItems, index]);
                    } else {
                      setSelectedItems(selectedItems.filter((idx) => idx !== index));
                    }
                  }}
                />
                <span>选择</span>
              </label>
            </div>

            <div className="review-block">
              <div className="surface-label">答案</div>
              <pre className="answer-block">{currentResult.answers?.[index]}</pre>
            </div>

            <div className="review-block">
              <div className="surface-label">标签</div>
              <div className="tag-row">
                {currentResult.tags?.[index]?.length ? (
                  currentResult.tags[index].map((tag) => <StatusPill key={`${index}-${tag}`}>{tag}</StatusPill>)
                ) : (
                  <span className="muted-text">暂无标签</span>
                )}
              </div>
            </div>

            <div className="review-block">
              <div className="surface-label">编辑标签</div>
              <div className="editable-tag-list">
                {getCurrentTagsForIndex(index).map((tag, tagIdx) => (
                  <div className="editable-tag-row" key={`${index}-${tagIdx}`}>
                    <Input
                      value={tag}
                      placeholder="输入或修改 tag"
                      onChange={(e) => updateEditableTag(index, tagIdx, e.target.value)}
                    />
                    <Button danger onClick={() => removeEditableTag(index, tagIdx)}>
                      删除
                    </Button>
                  </div>
                ))}
                <Button onClick={() => addEditableTag(index)} className="ghost-button">
                  添加标签
                </Button>
                {reviewTagOptions.length > 0 ? (
                  <div className="tag-row">
                    {reviewTagOptions.map((tag) => (
                      <Button
                        key={`${index}-${tag}`}
                        size="small"
                        className="suggestion-button"
                        onClick={() => applySuggestedTag(index, tag)}
                      >
                        {tag}
                      </Button>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          </Card>
        ))}
      </div>

      <div className="surface-card feedback-panel">
        <div>
          <div className="surface-emphasis">如果结果需要微调，可以先给出修正提示。</div>
          <p className="muted-text">例如忽略表头、重组问答口径，或限定某些段落不要入库。</p>
        </div>
        <TextArea
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder="例如：请忽略第一行表头，重新提取..."
          rows={3}
        />
        <Space wrap>
          <Button
            icon={<SendOutlined />}
            onClick={handleCorrection}
            disabled={!feedback}
            className="ghost-button"
          >
            发送修正
          </Button>
          <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleConfirm}>
            {selectedItems.length > 0 ? `确认入库选中的 ${selectedItems.length} 个项目` : '确认入库所有项目'}
          </Button>
        </Space>
      </div>
    </div>
  );

  const renderCategoryContent = () => (
    <div className="main-stack">
      <SectionIntro
        eyebrow="Library"
        title="知识分类"
        description="按分类浏览内容，比传统表格更轻，也更适合快速进入某个主题。"
        aside={<StatusPill tone="neutral">{categories.length} 个分类</StatusPill>}
      />
      <div className="category-grid">
        {categories.map((category) => (
          <button
            key={category}
            type="button"
            className="category-tile"
            onClick={() => {
              setSelectedCategory(category);
              fetchVaultDataByCategory(category);
              setStatus('knowledgeBase');
            }}
          >
            <div className="category-tile-icon">□</div>
            <div className="category-tile-name">{category}</div>
            <div className="category-tile-hint">进入该分类</div>
          </button>
        ))}
      </div>
      <div className="inline-actions">
        <Button onClick={fetchCategories} className="ghost-button">
          刷新分类
        </Button>
        <Button
          type="primary"
          onClick={() => {
            setSelectedCategory('');
            fetchVaultDataByCategory();
            setStatus('knowledgeBase');
          }}
        >
          查看所有知识
        </Button>
      </div>
    </div>
  );

  const renderKnowledgeContent = () => (
    <div className="main-stack">
      <SectionIntro
        eyebrow="Vault"
        title={selectedCategory ? `知识库 · ${selectedCategory}` : '所有知识'}
        description={`当前范围共 ${finalItems.length} 条记录。点击卡片可展开答案详情。`}
        aside={<StatusPill tone="success">{finalItems.length} 条记录</StatusPill>}
      />

      <div className="surface-card">
        <div className="surface-row">
          <div>
            <div className="surface-label">Tag 概览</div>
            <div className="surface-emphasis">{sortedKnowledgeTags.length} 个标签</div>
          </div>
          <Space wrap>
            <Button onClick={() => fetchVaultDataByCategory(selectedCategory)} className="ghost-button">
              刷新
            </Button>
            <Button onClick={() => setStatus('categories')} className="ghost-button">
              返回分类
            </Button>
          </Space>
        </div>
        <div className="tag-row">
          {sortedKnowledgeTags.length > 0 ? (
            sortedKnowledgeTags.map(({ tag, count }) => (
              <span key={tag} className="tag-chip">
                <span>{tag}</span>
                <strong>{count}</strong>
              </span>
            ))
          ) : (
            <span className="muted-text">当前范围内还没有 tag 数据</span>
          )}
        </div>
      </div>

      {finalItems.length === 0 ? (
        <div className="surface-card">
          <EmptyState icon="□" title="该分类下暂无知识内容" description="先从左侧录入素材，或切换分类查看。" />
        </div>
      ) : (
        <div className="knowledge-grid">
          {finalItems.map((item) => (
            <Card key={item.id} className="knowledge-card" bordered={false}>
              <button
                type="button"
                className="knowledge-card-toggle"
                onClick={() => {
                  const nextExpanded = new Set(expandedCards);
                  if (nextExpanded.has(item.id)) nextExpanded.delete(item.id);
                  else nextExpanded.add(item.id);
                  setExpandedCards(nextExpanded);
                }}
              >
                <div className="knowledge-card-top">
                  <div>
                    <div className="knowledge-question">{item.question}</div>
                    <div className="knowledge-meta">
                      <StatusPill>{item.category}</StatusPill>
                      <span>{new Date(item.created_at).toLocaleDateString('zh-CN')}</span>
                    </div>
                  </div>
                  <Popconfirm
                    title="确定要删除这条知识吗？"
                    description="删除后将无法恢复"
                    onConfirm={() => handleDeleteItem(item.id)}
                    okText="确定"
                    cancelText="取消"
                  >
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      size="small"
                      onClick={(e) => e.stopPropagation()}
                    >
                      删除
                    </Button>
                  </Popconfirm>
                </div>
                {expandedCards.has(item.id) ? (
                  <div className="answer-block answer-block-plain">{item.answer}</div>
                ) : null}
              </button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );

  const renderQueueSidebar = () => (
    <div className="sidebar-panel">
      <div className="sidebar-panel-header">
        <div>
          <div className="sidebar-title">任务队列</div>
          <div className="sidebar-copy">查看当前处理顺序与结果状态。</div>
        </div>
        <StatusPill>{taskQueue.length} 个任务</StatusPill>
      </div>

      {taskQueue.length === 0 ? (
        <EmptyState icon="◻" title="暂无任务" description="提交 URL 或文本后，这里会显示处理进度。" compact />
      ) : (
        <div className="queue-list">
          {taskQueue.map((task) => (
            <div key={task.id} className={cx('queue-card', `queue-card-${task.status}`)}>
              <div className="queue-card-title">
                {task.title.length > 36 ? `${task.title.slice(0, 36)}...` : task.title}
              </div>
              <div className="queue-card-meta">
                <span>{task.category}</span>
                <StatusPill
                  tone={
                    task.status === 'completed'
                      ? 'success'
                      : task.status === 'failed'
                        ? 'danger'
                        : task.status === 'processing'
                          ? 'info'
                          : 'warning'
                  }
                >
                  {TASK_STATUS_META[task.status]}
                </StatusPill>
              </div>
              {task.error ? <div className="queue-error">{task.error}</div> : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const renderChatSidebar = () => (
    <div className="chat-shell">
      <div className="chat-header">
        <div className="sidebar-panel-header">
          <div>
            <div className="sidebar-title">对话助手</div>
            <div className="sidebar-copy">基于知识库进行检索式问答。</div>
          </div>
          <Space>
            <Button size="small" onClick={handleNewConversation}>
              新建
            </Button>
            <Button size="small" onClick={() => setShowChatSidebar(false)}>
              关闭
            </Button>
          </Space>
        </div>

        <div className="chat-filters">
          <div className="field-group">
            <label>历史会话</label>
            <div className="conversation-list">
              {chatConversations.length > 0 ? (
                chatConversations.map((conversation) => (
                  <div key={conversation.id} className="conversation-item">
                    <Button
                      type={conversation.id === currentChatId ? 'primary' : 'default'}
                      onClick={() => loadChatConversation(conversation.id)}
                      className="conversation-button"
                    >
                      {conversation.title}
                    </Button>
                    <Popconfirm
                      title="删除这个会话？"
                      onConfirm={() => handleDeleteConversation(conversation.id)}
                      okText="删除"
                      cancelText="取消"
                    >
                      <Button danger size="small">
                        删
                      </Button>
                    </Popconfirm>
                  </div>
                ))
              ) : (
                <span className="muted-text">暂无历史会话</span>
              )}
            </div>
          </div>

          <div className="field-group">
            <label>检索分类</label>
            <Select
              allowClear
              value={selectedChatCategory || undefined}
              placeholder="不过滤分类"
              onChange={(value) => setSelectedChatCategory(value || '')}
              options={categories.map((category) => ({ label: category, value: category }))}
            />
          </div>

          <div className="field-group">
            <label>检索标签</label>
            <Select
              mode="multiple"
              allowClear
              value={selectedChatTags}
              placeholder="不过滤标签"
              onChange={(value) => setSelectedChatTags(value)}
              options={chatTagOptions.map((tag) => ({ label: tag, value: tag }))}
            />
          </div>
        </div>
      </div>

      <div className="chat-messages" ref={messagesEndRef}>
        {chatMessages.length === 0 ? (
          <EmptyState icon="◎" title="开始与助手对话" description="问题会结合当前分类和标签筛选来回答。" compact />
        ) : (
          chatMessages.map((chatMessage) => (
            <div
              key={chatMessage.id}
              className={cx(
                'chat-row',
                chatMessage.type === 'user' ? 'chat-row-user' : 'chat-row-ai',
              )}
            >
              {chatMessage.type === 'ai' ? (
                <QuestionCircleOutlined className="chat-avatar" />
              ) : null}
              <div className={cx('chat-bubble', chatMessage.type === 'user' && 'chat-bubble-user')}>
                {chatMessage.loading ? (
                  <div className="loading-inline">
                    <Spin size="small" indicator={<LoadingOutlined spin />} />
                    <span>助手正在思考...</span>
                  </div>
                ) : chatMessage.type === 'user' ? (
                  <Typography.Text>{chatMessage.content}</Typography.Text>
                ) : (
                  <div className="markdown-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{chatMessage.content}</ReactMarkdown>
                  </div>
                )}
              </div>
              {chatMessage.type === 'user' ? <UserOutlined className="chat-avatar" /> : null}
            </div>
          ))
        )}
      </div>

      <div className="chat-input-wrap">
        <TextArea
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          placeholder="输入你的问题..."
          rows={3}
          onPressEnter={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSendMessage();
            }
          }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={handleSendMessage}
          loading={isLoading}
          disabled={isLoading || !chatInput.trim()}
          block
        >
          发送
        </Button>
      </div>
    </div>
  );

  return (
    <Layout className="app-shell">
      <Sider width={320} theme="light" className="left-rail">
        <div className="brand-block">
          <div className="brand-mark">KH</div>
          <div>
            <div className="brand-title">Knowledge Helper</div>
            <div className="brand-copy">采集、整理、问答，一次完成。</div>
          </div>
        </div>

        <div className="rail-section">
          <div className="rail-section-title">输入来源</div>
          <Select
            size="large"
            value={inputMode}
            onChange={setInputMode}
            options={[
              { label: 'URL 链接', value: 'url' },
              { label: '粘贴文本', value: 'text' },
            ]}
          />
        </div>

        <div className="rail-section">
          <div className="rail-section-title">{inputMode === 'url' ? 'URL 地址' : '笔记文本'}</div>
          {inputMode === 'url' ? (
            <Input
              placeholder="https://www.bilibili.com/..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              size="large"
            />
          ) : (
            <TextArea
              placeholder="直接粘贴你的笔记、摘要、会议记录或其他文本内容"
              value={pastedText}
              onChange={(e) => setPastedText(e.target.value)}
              rows={8}
            />
          )}
        </div>

        <div className="rail-section">
          <div className="rail-section-title">指定数据库类别</div>
          <Select
            placeholder="请选择类别"
            size="large"
            value={selectedCategory}
            onChange={setSelectedCategory}
            options={categories.map((category) => ({ label: category, value: category }))}
            popupRender={(menu) => (
              <>
                {menu}
                <Button
                  type="text"
                  icon={<PlusOutlined />}
                  onClick={() => setAddCategoryModal(true)}
                  className="add-category-button"
                >
                  添加新类别
                </Button>
              </>
            )}
          />
        </div>

        <div className="rail-section">
          <div className="rail-section-title">提取模式</div>
          <Select
            size="large"
            value={extractMode}
            onChange={setExtractMode}
            options={[
              { label: '提取图文', value: 'text_and_images' },
              { label: '只提取文字', value: 'text_only' },
            ]}
          />
        </div>

        <Button type="primary" size="large" onClick={handleStart} className="primary-action">
          开始处理
        </Button>

        <div className="rail-divider" />

        <div className="rail-actions">
          <Button
            size="large"
            icon={<FolderOpenOutlined />}
            onClick={() => setStatus('categories')}
            className="secondary-action"
          >
            查看知识库
          </Button>
          <Button
            size="large"
            icon={<MessageOutlined />}
            onClick={() => setShowChatSidebar((value) => !value)}
            className="secondary-action"
          >
            对话助手
          </Button>
        </div>
      </Sider>

      <Layout className="main-layout">
        <Content className="main-content">
          {status === 'idle' && renderIdleContent()}
          {status === 'processing' && renderProcessingContent()}
          {confirmStatus === 'confirming' && renderProcessingContent()}
          {status === 'reviewing' && currentResult && renderReviewContent()}
          {status === 'categories' && renderCategoryContent()}
          {status === 'knowledgeBase' && renderKnowledgeContent()}
        </Content>
      </Layout>

      <div
        className={cx('resize-handle', isResizing && 'resize-handle-active')}
        onMouseDown={handleMouseDown}
      />

      <aside className="right-rail" style={{ width: sidebarWidth }} ref={sidebarRef}>
        {showChatSidebar ? renderChatSidebar() : renderQueueSidebar()}
      </aside>

      <Modal
        title="添加新类别"
        open={addCategoryModal}
        onOk={handleAddCategory}
        onCancel={() => setAddCategoryModal(false)}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="类别名称"
            rules={[{ required: true, message: '请输入类别名称' }]}
          >
            <Input placeholder="例如：技术文档" />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  );
}

export default App;