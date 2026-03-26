import React, { useState, useEffect, useRef } from 'react';
import { Layout, Input, Select, Button, Space, Card, message, Modal, Form, Progress, Popconfirm, Typography } from 'antd';
import { PlusOutlined, SendOutlined, CheckCircleOutlined, FolderOpenOutlined, DeleteOutlined, MessageOutlined, QuestionCircleOutlined, UserOutlined } from '@ant-design/icons';

const { Sider, Content } = Layout;
const API_BASE = 'http://localhost:8000/api';

const DataManagerPage = () => {
  const [categories, setCategories] = useState([]);
  const [currentResult, setCurrentResult] = useState(null);
  const [feedback, setFeedback] = useState('');
  const [finalItems, setFinalItems] = useState([]);
  const [status, setStatus] = useState('idle'); // idle, processing, reviewing, categories, knowledgeBase
  const [url, setUrl] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('');
  const [addCategoryModal, setAddCategoryModal] = useState(false);
  const [selectedItems, setSelectedItems] = useState([]);
  const [form] = Form.useForm();
  const [expandedCards, setExpandedCards] = useState(new Set());
  const [confirmProgress, setConfirmProgress] = useState(0);
  const [confirmStatus, setConfirmStatus] = useState('idle'); // idle, confirming
  const [taskQueue, setTaskQueue] = useState([]);
  const [currentTaskId, setCurrentTaskId] = useState(null);
  const [deleteModalVisible, setDeleteModalVisible] = useState(false);
  const [itemToDelete, setItemToDelete] = useState(null);
  
  // 聊天功能状态
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [selectedChatCategory, setSelectedChatCategory] = useState('');
  const [showChatSidebar, setShowChatSidebar] = useState(false);
  const messagesEndRef = useRef(null);

  // 获取数据库类别
  useEffect(() => {
    fetchCategories();
  }, []);

  // 获取知识库数据（根据类别）
  const fetchVaultDataByCategory = async (category = null) => {
    try {
      const url = category 
        ? `${API_BASE}/vault?category=${encodeURIComponent(category)}` 
        : `${API_BASE}/vault`;
      const response = await fetch(url);
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

  const fetchVaultData = async () => {
    await fetchVaultDataByCategory();
  };

  // Delete vault item
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

  // 开始处理URL
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');

  // 生成任务ID
  const generateTaskId = () => {
    return Date.now().toString(36) + Math.random().toString(36).substr(2);
  };

  // 处理队列中的任务
  const processNextTask = () => {
    const nextTask = taskQueue.find(task => task.status === 'pending');
    if (nextTask) {
      setCurrentTaskId(nextTask.id);
      processTask(nextTask);
    } else {
      setCurrentTaskId(null);
    }
  };

  // 处理单个任务
  const processTask = async (task) => {
    // 更新任务状态为处理中
    setTaskQueue(prev => prev.map(t => 
      t.id === task.id ? { ...t, status: 'processing' } : t
    ));

    setStatus('processing');
    setProgress(0);
    setProgressMessage('开始处理URL');
    
    try {
      const response = await fetch(`${API_BASE}/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: task.url, category: task.category || '未分类' }),
      });

      if (!response.ok) {
        throw new Error('网络响应错误');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      let buffer = '';
      let done = false;
      let timeoutId;
      
      // 设置超时处理
      const timeoutPromise = new Promise((_, reject) => {
        timeoutId = setTimeout(() => {
          reject(new Error('处理超时'));
        }, 300000); // 2分钟超时
      });

      // 同时等待读取完成或超时
      const readPromise = (async () => {
        while (!done) {
          const { value, done: doneReading } = await reader.read();
          done = doneReading;
          const chunk = decoder.decode(value, { stream: true });

          // 处理SSE事件 - 使用缓冲区处理不完整的事件
          const events = (buffer + chunk).split('\n\n');
          buffer = events.pop() || ''; // 保留最后一个可能不完整的事件

          for (const event of events) {
            if (event.startsWith('data:')) {
              const dataStr = event.substring(5).trim();
              // 跳过空数据和[DONE]信号
              if (dataStr && dataStr !== '[DONE]') {
                try {
                  const data = JSON.parse(dataStr);
                  console.log('收到SSE数据:', data);
                  if (data.status === 'processing') {
                    setProgress(data.progress);
                    setProgressMessage(data.message);
                    // 重置超时计时器
                    clearTimeout(timeoutId);
                    timeoutId = setTimeout(() => {
                      reader.cancel();
                    }, 120000); // 2分钟超时
                  } else if (data.status === 'completed') {
                    if (data.result.error) {
                      // 处理后端返回的错误
                      message.error(data.result.error);
                      // 更新任务状态为失败
                      setTaskQueue(prev => prev.map(t =>
                        t.id === task.id ? { ...t, status: 'failed', error: data.result.error } : t
                      ));
                      setStatus('idle');
                    } else {
                      // 处理成功结果
                      setCurrentResult(data.result);
                      setStatus('reviewing');
                      // 更新任务状态为完成
                      setTaskQueue(prev => prev.map(t =>
                        t.id === task.id ? {
                          ...t,
                          status: 'completed',
                          title: data.result.title || data.result.preview?.split('\n')[0] || task.title
                        } : t
                      ));
                    }
                  } else if (data.status === 'error') {
                    message.error(data.message);
                    // 更新任务状态为失败
                    setTaskQueue(prev => prev.map(t =>
                      t.id === task.id ? { ...t, status: 'failed', error: data.message } : t
                    ));
                    setStatus('idle');
                  }
                } catch (e) {
                  console.error('解析SSE数据失败:', e, '原始数据:', dataStr);
                }
              }
            }
          }
        }
      })();

      await Promise.race([readPromise, timeoutPromise]);
    } catch (error) {
      message.error(`处理失败: ${error.message}`);
      // 更新任务状态为失败
      setTaskQueue(prev => prev.map(t => 
        t.id === task.id ? { ...t, status: 'failed', error: error.message } : t
      ));
      setStatus('idle');
    } finally {
      // 处理下一个任务
      setTimeout(() => {
        processNextTask();
      }, 500);
    }
  };

  // 开始处理URL
  const handleStart = () => {
    if (!url) {
      message.error('请输入URL地址');
      return;
    }

    if (!selectedCategory) {
      message.error('请选择类别');
      return;
    }

    // 生成任务标题
    let taskTitle = url;
    // 尝试从URL中提取更友好的标题
    try {
      const urlObj = new URL(url);
      taskTitle = urlObj.hostname + urlObj.pathname;
    } catch (e) {
      // 无效URL，使用原始值
    }

    // 创建新任务
    const newTask = {
      id: generateTaskId(),
      url,
      category: selectedCategory,
      title: taskTitle,
      status: 'pending', // pending, processing, completed, failed
      created: new Date().toISOString()
    };

    // 添加到任务队列
    setTaskQueue(prev => [...prev, newTask]);

    // 如果当前没有正在处理的任务，直接处理新任务
    if (!currentTaskId) {
      // 直接处理新任务，而不是依赖taskQueue状态
      setCurrentTaskId(newTask.id);
      processTask(newTask);
    }

    // 清空输入
    setUrl('');
    setSelectedCategory('');
  };

  // 提交修正建议
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
    } catch (error) {
      message.error('修正失败');
    }
  };

  // 确认入库
  const handleConfirm = async () => {
    if (!currentResult) return;

    try {
      // 确定要提交的项目索引
      const indicesToSubmit = selectedItems.length > 0 
        ? selectedItems 
        : Array.from({ length: currentResult.questions?.length || 0 }, (_, i) => i);

      if (indicesToSubmit.length === 0) {
        message.error('没有要提交的项目');
        return;
      }

      // 设置确认状态和初始进度
      setConfirmStatus('confirming');
      setConfirmProgress(0);

      // 逐个提交项目
      let successCount = 0;
      const totalItems = indicesToSubmit.length;
      
      for (let i = 0; i < indicesToSubmit.length; i++) {
        const index = indicesToSubmit[i];
        
        // 更新进度
        const progress = Math.round((i / totalItems) * 100);
        setConfirmProgress(progress);
        
        const response = await fetch(`${API_BASE}/commit`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            id: currentResult.id,
            question: currentResult.questions[index],
            answer: currentResult.answers[index],
            tags: currentResult.tags[index],
            category: currentResult.category,
          }),
        });

        const data = await response.json();
        if (data.status === 'success') {
          successCount++;
        }
      }

      // 设置最终进度
      setConfirmProgress(100);

      if (successCount > 0) {
        message.success(`成功入库 ${successCount} 个项目`);
        await fetchVaultData();
        setStatus('idle');
        setCurrentResult(null);
        setSelectedItems([]);
      } else {
        message.error('入库失败');
      }
      
      // 重置确认状态
      setTimeout(() => {
        setConfirmStatus('idle');
        setConfirmProgress(0);
      }, 1000);
    } catch (error) {
      message.error('入库失败，请检查网络连接');
      setConfirmStatus('idle');
      setConfirmProgress(0);
    }
  };

  // 添加新类别
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

  // 发送聊天消息
  const handleSendMessage = async () => {
    if (!chatInput.trim()) return;

    const userMessage = {
      id: Date.now(),
      content: chatInput,
      type: 'user'
    };

    setChatMessages(prev => [...prev, userMessage]);
    setChatInput('');
    setIsLoading(true);

    try {
      const response = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: chatInput, referenced_ids: [] }),
      });

      if (!response.ok) {
        throw new Error('网络响应错误');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      
      let aiMessageId = Date.now() + 1;
      let aiMessageContent = '';
      
      setChatMessages(prev => [...prev, {
        id: aiMessageId,
        content: '',
        type: 'ai'
      }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n\n');

        for (const line of lines) {
          if (line.startsWith('data:')) {
            const dataStr = line.substring(5).trim();
            if (dataStr && dataStr !== '[DONE]') {
              try {
                const data = JSON.parse(dataStr);
                if (data.content) {
                  aiMessageContent += data.content;
                  setChatMessages(prev => prev.map(msg => 
                    msg.id === aiMessageId ? { ...msg, content: aiMessageContent } : msg
                  ));
                }
              } catch (e) {
                console.error('解析SSE数据失败:', e);
              }
            }
          }
        }
      }
    } catch (error) {
      console.error('发送消息失败:', error);
      message.error('发送消息失败，请检查网络连接');
      setChatMessages(prev => prev.slice(0, -1)); // 移除AI消息占位符
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Layout style={{ height: '100vh', width: '100%', display: 'flex', margin: 0, padding: 0 }}>
      {/* 左侧数据上传面板 */}
      <Sider width={280} theme="light" style={{ borderRight: '1px solid #f0f0f0', padding: '24px', background: '#fafafa', overflowY: 'auto' }}>
        <div style={{ marginBottom: '24px' }}>
          <h2 style={{ margin: '0 0 8px 0', fontSize: '20px', fontWeight: 600, color: '#262626' }}>数据上传</h2>
          <p style={{ margin: '0', fontSize: '13px', color: '#8c8c8c' }}>支持 B站、小红书等平台</p>
        </div>

        <Space orientation="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <label style={{ fontSize: '13px', fontWeight: 500, color: '#595959', display: 'block', marginBottom: '8px' }}>输入URL地址</label>
            <Input
              placeholder="https://www.bbilibili.com/..."
              value={url}
              onChange={e => setUrl(e.target.value)}
              size="large"
              style={{ borderRadius: '6px' }}
            />
          </div>

          <div>
            <label style={{ fontSize: '13px', fontWeight: 500, color: '#595959', display: 'block', marginBottom: '8px' }}>指定数据库类别 <span style={{ color: '#ff4d4f' }}>*</span></label>
            <Select
              style={{ width: '100%' }}
              placeholder="请选择类别"
              size="large"
              value={selectedCategory}
              onChange={setSelectedCategory}
              options={categories.map(c => ({ label: c, value: c }))}
              popupRender={(menu) => (
                <>
                  {menu}
                  <Button
                    type="text"
                    icon={<PlusOutlined />}
                    onClick={() => setAddCategoryModal(true)}
                    style={{ width: '100%', textAlign: 'left' }}
                  >
                    添加新类别
                  </Button>
                </>
              )}
            />
          </div>

          <Button
            type="primary"
            block
            size="large"
            onClick={handleStart}
            style={{ height: '44px', borderRadius: '6px', fontSize: '15px', fontWeight: 500 }}
          >
            开始处理
          </Button>

          <div style={{ height: '1px', background: '#e8e8e8', margin: '8px 0' }}></div>

          <div>
            <label style={{ fontSize: '13px', fontWeight: 500, color: '#595959', display: 'block', marginBottom: '8px' }}>知识库管理</label>
          </div>

          <Button
            block
            size="large"
            icon={<FolderOpenOutlined />}
            onClick={() => setStatus('categories')}
            style={{ height: '44px', borderRadius: '6px', fontSize: '15px', fontWeight: 500 }}
          >
            查看知识库
          </Button>
          
          <Button
            block
            size="large"
            icon={<MessageOutlined />}
            onClick={() => setShowChatSidebar(!showChatSidebar)}
            style={{ height: '44px', borderRadius: '6px', fontSize: '15px', fontWeight: 500 }}
          >
            对话助手
          </Button>
        </Space>
      </Sider>

      {/* 中间内容区域 */}
      <Layout style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <Content style={{ padding: '32px', background: '#ffffff', overflow: 'auto', flex: 1 }}>
          {status === 'idle' && (
            <div style={{ textAlign: 'center', marginTop: '120px', color: '#999' }}>
              <div style={{ fontSize: '64px', marginBottom: '24px' }}>📚</div>
              <p style={{ fontSize: '18px' }}>在左侧输入URL开始处理，或点击"查看知识库"浏览已有内容</p>
            </div>
          )}

          {status === 'processing' && (
            <div style={{ textAlign: 'center', marginTop: '120px' }}>
              <Card style={{ maxWidth: '500px', margin: '0 auto', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}>
                <div style={{ fontSize: '48px', marginBottom: '24px' }}>⏳</div>
                <Progress percent={progress} status="active" strokeColor={{ '0%': '#108ee9', '100%': '#87d068' }} />
                <p style={{ marginTop: '20px', fontSize: '16px', color: '#666' }}>{progressMessage}</p>
              </Card>
            </div>
          )}

          {confirmStatus === 'confirming' && (
            <div style={{ textAlign: 'center', marginTop: '120px' }}>
              <Card style={{ maxWidth: '500px', margin: '0 auto', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}>
                <div style={{ fontSize: '48px', marginBottom: '24px' }}>💾</div>
                <h3 style={{ marginBottom: '20px' }}>确认入库进度</h3>
                <Progress percent={confirmProgress} status="active" strokeColor={{ '0%': '#108ee9', '100%': '#52c41a' }} />
                <p style={{ marginTop: '20px', fontSize: '16px', color: '#666' }}>正在将项目添加到知识库...</p>
              </Card>
            </div>
          )}

          {status === 'reviewing' && currentResult && (
            <Card
              title={
                <span>
                  <span style={{ fontSize: '18px', fontWeight: 500 }}>处理结果预览</span>
                  <span style={{ fontSize: '14px', color: '#666', marginLeft: '12px' }}>
                    (共 {currentResult.questions?.length || 0} 个问题)
                  </span>
                </span>
              }
              extra={<span style={{ background: '#fff7e6', color: '#fa8c16', padding: '4px 12px', borderRadius: '4px', fontSize: '14px' }}>待确认</span>}
              style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.06)' }}
            >
              <div style={{ marginBottom: '24px', padding: '12px', background: '#f6f8fa', borderRadius: '6px' }}>
                <span style={{ color: '#666', fontSize: '14px' }}>类别：</span>
                <span style={{ fontWeight: 500, marginLeft: '8px', color: '#262626' }}>{currentResult.category}</span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(500px, 1fr))', gap: '20px' }}>
                {currentResult.questions && currentResult.questions.map((question, index) => (
                  <Card
                    key={index}
                    style={{
                      borderLeft: '4px solid #1890ff',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                      borderRadius: '6px'
                    }}
                  >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                    <div style={{ fontSize: '16px', fontWeight: 500, color: '#262626' }}>
                      <span style={{ color: '#1890ff', marginRight: '8px' }}>#{index + 1}</span>
                    </div>
                    <div>
                      <input
                        type="checkbox"
                        checked={selectedItems.includes(index)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedItems([...selectedItems, index]);
                          } else {
                            setSelectedItems(selectedItems.filter(idx => idx !== index));
                          }
                        }}
                        style={{ cursor: 'pointer' }}
                      />
                      <span style={{ marginLeft: '8px', fontSize: '14px', color: '#666', cursor: 'pointer', userSelect: 'none' }}>选择</span>
                    </div>
                  </div>
                  <div style={{ marginBottom: '16px', padding: '12px', background: '#fafafa', borderRadius: '4px', lineHeight: '1.6' }}>
                    <strong style={{ color: '#595959', fontSize: '14px', display: 'block', marginBottom: '6px' }}>问题：</strong>
                    {question}
                  </div>
                  <div style={{ marginBottom: '12px' }}>
                    <strong style={{ color: '#595959', fontSize: '14px' }}>答案：</strong>
                  </div>
                  <pre style={{ background: '#f6f8fa', padding: '12px', marginBottom: '12px', borderRadius: '4px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '14px', lineHeight: '1.6' }}>
                    {currentResult.answers && currentResult.answers[index]}
                  </pre>
                  <div>
                    <strong style={{ color: '#595959', fontSize: '14px' }}>标签：</strong>
                    {currentResult.tags && currentResult.tags[index] && currentResult.tags[index].length > 0 ? (
                      <div style={{ marginTop: '6px' }}>
                        {currentResult.tags[index].map((tag, tagIdx) => (
                          <span key={tagIdx} style={{
                            display: 'inline-block',
                            background: '#e6f7ff',
                            color: '#096dd9',
                            padding: '2px 8px',
                            borderRadius: '4px',
                            fontSize: '12px',
                            marginRight: '6px',
                            marginBottom: '4px'
                          }}>
                            {tag}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span style={{ color: '#999', fontSize: '14px' }}>无</span>
                    )}
                  </div>
                </Card>
              ))}
              </div>

              <div style={{ marginTop: '24px', padding: '20px', background: '#f9f9f9', borderRadius: '8px', border: '1px solid #e8e8e8' }}>
                <p style={{ marginBottom: '12px', fontSize: '14px', color: '#666' }}>如果不满意，请输入修正提示：</p>
                <Input.TextArea
                  value={feedback}
                  onChange={e => setFeedback(e.target.value)}
                  placeholder="例如：请忽略第一行表头，重新提取..."
                  rows={3}
                  style={{ marginBottom: '12px' }}
                />
                <Space style={{ marginTop: '8px' }}>
                  <Button
                    icon={<SendOutlined />}
                    onClick={handleCorrection}
                    disabled={!feedback}
                    style={{ minWidth: '100px' }}
                  >
                    发送修正
                  </Button>
                  <Button
                    type="primary"
                    icon={<CheckCircleOutlined />}
                    onClick={handleConfirm}
                    style={{ minWidth: '140px' }}
                  >
                    {selectedItems.length > 0 ? `确认入库选中的 ${selectedItems.length} 个项目` : '确认入库所有项目'}
                  </Button>
                </Space>
              </div>
            </Card>
          )}

          {status === 'categories' && (
            <Card
              title={
                <span>
                  <span style={{ fontSize: '18px', fontWeight: 500 }}>知识库分类</span>
                  <span style={{ fontSize: '14px', color: '#666', marginLeft: '12px' }}>
                    ({categories.length} 个分类)
                  </span>
                </span>
              }
              extra={<Button size="small" onClick={fetchCategories}>刷新</Button>}
              style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.06)' }}
            >
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '20px' }}>
                {categories.map((category) => (
                  <Card
                    key={category}
                    hoverable
                    onClick={() => {
                      setSelectedCategory(category);
                      fetchVaultDataByCategory(category);
                      setStatus('knowledgeBase');
                    }}
                    style={{ borderRadius: '8px', textAlign: 'center', padding: '16px' }}
                  >
                    <div style={{ fontSize: '48px', marginBottom: '12px' }}>📁</div>
                    <div style={{ fontSize: '16px', fontWeight: 500, color: '#262626' }}>{category}</div>
                    <div style={{ fontSize: '12px', color: '#999', marginTop: '4px' }}>点击查看内容</div>
                  </Card>
                ))}
              </div>
              <Button
                type="primary"
                style={{ marginTop: '24px', minWidth: '140px', height: '40px', borderRadius: '6px' }}
                onClick={() => {
                  setSelectedCategory('');
                  fetchVaultDataByCategory();
                  setStatus('knowledgeBase');
                }}
              >
                查看所有知识
              </Button>
            </Card>
          )}

          {status === 'knowledgeBase' && (
            <Card
              title={
                <span>
                  <span style={{ fontSize: '18px', fontWeight: 500 }}>
                    {selectedCategory ? `知识库 - ${selectedCategory}` : '所有知识'}
                  </span>
                  <span style={{ fontSize: '14px', color: '#666', marginLeft: '12px' }}>
                    ({finalItems.length} 条记录)
                  </span>
                </span>
              }
              extra={
                <Space>
                  <Button size="small" onClick={() => fetchVaultDataByCategory(selectedCategory)}>刷新</Button>
                  <Button size="small" onClick={() => setStatus('categories')}>返回分类</Button>
                </Space>
              }
              style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.06)' }}
            >
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(450px, 1fr))', gap: '20px' }}>
                {finalItems.map((item) => (
                  <Card
                    key={item.id}
                    hoverable
                    style={{
                      borderLeft: '4px solid #1890ff',
                      borderRadius: '8px',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.04)'
                    }}
                  >
                    <div style={{ cursor: 'pointer' }} onClick={() => {
                      const newExpanded = new Set(expandedCards);
                      if (newExpanded.has(item.id)) {
                        newExpanded.delete(item.id);
                      } else {
                        newExpanded.add(item.id);
                      }
                      setExpandedCards(newExpanded);
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                        <h4 style={{ margin: '0', fontSize: '15px', lineHeight: '1.4', flex: 1, marginRight: '12px' }}>{item.question}</h4>
                        <Space>
                          <span style={{ fontSize: '12px', color: '#999', whiteSpace: 'nowrap' }}>
                            {new Date(item.created_at).toLocaleDateString('zh-CN')}
                          </span>
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
                              style={{ marginLeft: '8px' }}
                              onClick={(e) => e.stopPropagation()}
                            >
                              删除
                            </Button>
                          </Popconfirm>
                        </Space>
                      </div>
                      <div style={{ fontSize: '12px', color: '#999', marginBottom: '8px' }}>
                        <span style={{ background: '#f0f0f0', padding: '2px 8px', borderRadius: '4px' }}>{item.category}</span>
                      </div>
                      {expandedCards.has(item.id) && (
                        <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid #f0f0f0' }}>
                          <div style={{ fontSize: '14px', color: '#595959', marginBottom: '8px', fontWeight: 500 }}>答案：</div>
                          <pre style={{ background: '#f6f8fa', padding: '12px', borderRadius: '4px', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '14px', lineHeight: '1.6', margin: 0 }}>
                            {item.answer}
                          </pre>
                        </div>
                      )}
                    </div>
                  </Card>
                ))}
              </div>
              {finalItems.length === 0 && (
                <div style={{ textAlign: 'center', padding: '60px 20px', color: '#999' }}>
                  <div style={{ fontSize: '64px', marginBottom: '16px' }}>📭</div>
                  <p style={{ fontSize: '16px' }}>该分类下暂无知识内容</p>
                </div>
              )}
            </Card>
          )}


        </Content>
      </Layout>

      {/* 右侧任务队列和聊天侧边栏 */}
      <Sider width={280} theme="light" style={{ borderLeft: '1px solid #f0f0f0', background: '#fafafa', overflowY: 'auto' }}>
        {!showChatSidebar ? (
          <div style={{ padding: '24px' }}>
            <div style={{ marginBottom: '16px' }}>
              <h2 style={{ margin: '0 0 8px 0', fontSize: '18px', fontWeight: 600, color: '#262626' }}>任务队列</h2>
              <span style={{ fontSize: '12px', color: '#8c8c8c', background: '#f0f0f0', padding: '2px 8px', borderRadius: '4px' }}>
                {taskQueue.length} 个任务
              </span>
            </div>
            {taskQueue.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
                <div style={{ fontSize: '48px', marginBottom: '12px' }}>📋</div>
                <p style={{ fontSize: '14px' }}>暂无任务</p>
              </div>
            ) : (
              <div>
                {taskQueue.map((task) => (
                  <Card
                    key={task.id}
                    size="small"
                    style={{
                      marginBottom: '12px',
                      borderLeft: task.status === 'processing' ? '3px solid #1890ff' :
                                 task.status === 'completed' ? '3px solid #52c41a' :
                                 task.status === 'failed' ? '3px solid #ff4d4f' : '3px solid #d9d9d9',
                      borderRadius: '6px',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                      cursor: task.status === 'completed' ? 'pointer' : 'default'
                    }}
                    onClick={() => {
                      if (task.status === 'completed') {
                        message.info('点击了已完成的任务');
                      }
                    }}
                  >
                    <div style={{ marginBottom: '8px' }}>
                      <div
                        style={{
                          fontSize: '14px',
                          fontWeight: 500,
                          color: task.status === 'completed' ? '#1890ff' : '#262626',
                          lineHeight: '1.4'
                        }}
                      >
                        {task.title.length > 30 ? task.title.substring(0, 30) + '...' : task.title}
                      </div>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px' }}>
                      <span style={{ color: '#8c8c8c' }}>{task.category}</span>
                      <span style={{
                        color: task.status === 'pending' ? '#faad14' :
                               task.status === 'processing' ? '#1890ff' :
                               task.status === 'completed' ? '#52c41a' : '#ff4d4f',
                        fontWeight: 500
                      }}>
                        {task.status === 'pending' && '等待中'}
                        {task.status === 'processing' && '处理中'}
                        {task.status === 'completed' && '已完成'}
                        {task.status === 'failed' && '失败'}
                      </span>
                    </div>
                    {task.error && (
                      <div style={{ fontSize: '11px', color: '#ff4d4f', marginTop: '8px', padding: '4px', background: '#fff2f0', borderRadius: '4px' }}>
                        {task.error.length > 40 ? task.error.substring(0, 40) + '...' : task.error}
                      </div>
                    )}
                  </Card>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '24px', borderBottom: '1px solid #e8e8e8' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h2 style={{ margin: '0', fontSize: '18px', fontWeight: 600, color: '#262626' }}>对话助手</h2>
                <Button size="small" onClick={() => setShowChatSidebar(false)}>关闭</Button>
              </div>
              <p style={{ margin: '0', fontSize: '13px', color: '#8c8c8c' }}>基于知识库的智能问答</p>
            </div>
            
            {/* 聊天消息区域 */}
            <div 
              style={{ 
                flex: 1, 
                overflowY: 'auto', 
                padding: '16px', 
                background: '#fafafa'
              }}
              ref={messagesEndRef}
            >
              {chatMessages.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '60px 20px', color: '#999' }}>
                  <div style={{ fontSize: '64px', marginBottom: '16px' }}>🤖</div>
                  <p style={{ fontSize: '16px' }}>开始与助手对话吧！</p>
                  <p style={{ fontSize: '14px', marginTop: '8px' }}>助手会基于知识库内容回答你的问题</p>
                </div>
              ) : (
                chatMessages.map((message) => (
                  <div 
                    key={message.id} 
                    style={{
                      display: 'flex',
                      marginBottom: '16px',
                      justifyContent: message.type === 'user' ? 'flex-end' : 'flex-start'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'flex-start' }}>
                      {message.type === 'ai' && (
                            <QuestionCircleOutlined style={{ fontSize: '18px', color: '#1890ff', marginRight: '8px', marginTop: '2px' }} />
                          )}
                      <div 
                        style={{
                          maxWidth: '70%',
                          padding: '12px 16px',
                          borderRadius: '16px',
                          backgroundColor: message.type === 'user' ? '#1890ff' : '#ffffff',
                          color: message.type === 'user' ? '#ffffff' : '#333333',
                          boxShadow: '0 1px 2px rgba(0,0,0,0.1)'
                        }}
                      >
                        <Typography.Text style={{ lineHeight: '1.6' }}>{message.content}</Typography.Text>
                      </div>
                      {message.type === 'user' && (
                        <UserOutlined style={{ fontSize: '18px', color: '#1890ff', marginLeft: '8px', marginTop: '2px' }} />
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* 输入区域 */}
            <div style={{ padding: '16px', borderTop: '1px solid #e8e8e8', background: '#ffffff' }}>
              <Input.TextArea
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                placeholder="输入你的问题..."
                rows={2}
                style={{ 
                  marginBottom: '12px',
                  resize: 'none',
                  borderRadius: '8px'
                }}
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
                style={{ borderRadius: '8px' }}
              >
                发送
              </Button>
            </div>
          </div>
        )}
      </Sider>

      {/* 添加新类别模态框 */}
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

};

export default DataManagerPage;