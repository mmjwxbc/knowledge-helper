import React, { useState, useEffect, useRef } from 'react';
import { Layout, Upload, Input, Select, Button, Space, Card, Table, message, Modal, Form, Progress } from 'antd';
import { UploadOutlined, PlusOutlined, SendOutlined, CheckCircleOutlined, FolderOpenOutlined } from '@ant-design/icons';

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
          
          // 处理SSE事件
          const events = chunk.split('\n\n');
          for (const event of events) {
            if (event.startsWith('data:')) {
              const dataStr = event.substring(5).trim();
              if (dataStr) {
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
                  console.error('解析SSE数据失败:', e);
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
      category: selectedCategory || '未分类',
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

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider width="35%" theme="light" style={{ borderRight: '1px solid #f0f0f0', padding: '20px' }}>
        <h3>数据上传与配置</h3>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <Upload.Dragger name="file" multiple={false} disabled>
            <p className="ant-upload-drag-icon"><UploadOutlined /></p>
            <p>文件上传暂不可用</p>
            <p>请使用URL输入</p>
          </Upload.Dragger>

          <div>
            <label>输入URL地址：</label>
            <Input
              placeholder="https://example.com"
              value={url}
              onChange={e => setUrl(e.target.value)}
              style={{ marginTop: '8px' }}
            />
          </div>

          <div>
            <label>指定数据库类别：</label>
            <Select
              style={{ width: '100%', marginTop: '8px' }}
              placeholder="选择类别"
              value={selectedCategory}
              onChange={setSelectedCategory}
              options={categories.map(c => ({ label: c, value: c }))}
              dropdownRender={(menu) => (
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
          >
            开始处理
          </Button>

          <Button
            block
            size="large"
            icon={<FolderOpenOutlined />}
            onClick={() => setStatus('categories')}
          >
            查看知识库
          </Button>
        </Space>
      </Sider>

      <Layout style={{ flex: 1 }}>
        <Content style={{ padding: '20px', background: '#fafafa', overflowY: 'auto', flex: 1 }}>
          {status === 'idle' && (
            <div style={{ textAlign: 'center', marginTop: '100px' }}>
              <p style={{ fontSize: '16px', color: '#888' }}>请在左侧输入URL以开始处理</p>
            </div>
          )}

          {status === 'processing' && (
            <div style={{ textAlign: 'center', marginTop: '100px' }}>
              <Card title="处理进度" style={{ maxWidth: '600px', margin: '0 auto' }}>
                <Progress percent={progress} status="active" />
                <p style={{ marginTop: '20px', color: '#666' }}>{progressMessage}</p>
              </Card>
            </div>
          )}

          {confirmStatus === 'confirming' && (
            <div style={{ textAlign: 'center', marginTop: '100px' }}>
              <Card title="确认入库进度" style={{ maxWidth: '600px', margin: '0 auto' }}>
                <Progress percent={confirmProgress} status="active" />
                <p style={{ marginTop: '20px', color: '#666' }}>正在将项目添加到数据库...</p>
              </Card>
            </div>
          )}

          {status === 'reviewing' && currentResult && (
            <Card title={`后端处理结果预览 (共 ${currentResult.questions?.length || 0} 个问题)`} extra={<span style={{ color: '#1890ff' }}>待确认</span>}>
              <div style={{ marginBottom: '16px' }}>
                <strong>类别：</strong> {currentResult.category}
              </div>
              
              {currentResult.questions && currentResult.questions.map((question, index) => (
                <Card key={index} style={{ marginBottom: '16px', borderLeft: '4px solid #1890ff' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <div>
                      <strong>问题 {index + 1}：</strong>
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
                      />
                      <span style={{ marginLeft: '8px' }}>选择</span>
                    </div>
                  </div>
                  <p style={{ marginBottom: '12px' }}>{question}</p>
                  <div style={{ marginBottom: '8px' }}>
                    <strong>答案：</strong>
                  </div>
                  <pre style={{ background: '#f5f5f5', padding: '10px', marginBottom: '8px' }}>
                    {currentResult.answers && currentResult.answers[index]}
                  </pre>
                  <div>
                    <strong>标签：</strong> {currentResult.tags && currentResult.tags[index] ? currentResult.tags[index].join(', ') : '无'}
                  </div>
                </Card>
              ))}
              
              <div style={{ marginTop: '20px' }}>
                <p>如果不满意，请输入修正提示：</p>
                <Input.TextArea
                  value={feedback}
                  onChange={e => setFeedback(e.target.value)}
                  placeholder="例如：请忽略第一行表头，重新提取..."
                />
                <Space style={{ marginTop: '15px' }}>
                  <Button icon={<SendOutlined />} onClick={handleCorrection} disabled={!feedback}>
                    发送修正
                  </Button>
                  <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleConfirm}>
                    {selectedItems.length > 0 ? `确认入库选中的 ${selectedItems.length} 个项目` : '确认入库所有项目'}
                  </Button>
                </Space>
              </div>
            </Card>
          )}

          {status === 'categories' && (
            <Card title="知识库分类" extra={<Button size="small" onClick={fetchCategories}>刷新</Button>}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '16px' }}>
                {categories.map((category) => (
                  <Card 
                    key={category} 
                    hoverable
                    onClick={() => {
                      setSelectedCategory(category);
                      fetchVaultDataByCategory(category);
                      setStatus('knowledgeBase');
                    }}
                  >
                    <Card.Meta 
                      title={category} 
                      description="点击查看该分类下的知识"
                    />
                  </Card>
                ))}
              </div>
              <Button 
                type="primary" 
                style={{ marginTop: '16px' }} 
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
              title={`知识库内容 ${selectedCategory ? ` - ${selectedCategory}` : ''}`} 
              extra={
                <Space>
                  <Button size="small" onClick={() => fetchVaultDataByCategory(selectedCategory)}>刷新</Button>
                  <Button size="small" onClick={() => setStatus('categories')}>返回分类</Button>
                </Space>
              }
            >
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))', gap: '16px' }}>
                {finalItems.map((item) => (
                  <Card 
                    key={item.id} 
                    hoverable
                    style={{ borderLeft: '4px solid #1890ff' }}
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
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h4 style={{ margin: '0 0 8px 0' }}>{item.question}</h4>
                        <span style={{ fontSize: '12px', color: '#888' }}>
                          {new Date(item.created_at).toLocaleDateString('zh-CN')}
                        </span>
                      </div>
                      <div style={{ fontSize: '12px', color: '#888', marginBottom: '8px' }}>
                        类别: {item.category}
                      </div>
                      {expandedCards.has(item.id) && (
                        <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid #f0f0f0' }}>
                          <strong>答案：</strong>
                          <pre style={{ background: '#f5f5f5', padding: '10px', marginTop: '8px' }}>
                            {item.answer}
                          </pre>
                        </div>
                      )}
                    </div>
                  </Card>
                ))}
              </div>
              {finalItems.length === 0 && (
                <div style={{ textAlign: 'center', padding: '40px' }}>
                  <p>该分类下暂无知识内容</p>
                </div>
              )}
            </Card>
          )}
        </Content>

        {/* 任务队列侧边栏 */}
        <Sider width="300px" theme="light" style={{ borderLeft: '1px solid #f0f0f0', padding: '20px' }}>
          <h3>任务队列</h3>
          {taskQueue.length === 0 ? (
            <p style={{ color: '#888', marginTop: '20px' }}>暂无任务</p>
          ) : (
            <div style={{ marginTop: '20px' }}>
              {taskQueue.map((task) => (
                <Card 
                  key={task.id} 
                  style={{
                    marginBottom: '10px',
                    borderLeft: task.status === 'processing' ? '4px solid #1890ff' : 
                               task.status === 'completed' ? '4px solid #52c41a' : 
                               task.status === 'failed' ? '4px solid #ff4d4f' : '4px solid #d9d9d9'
                  }}
                >
                  <div 
                    style={{ 
                      fontSize: '14px', 
                      fontWeight: 'bold', 
                      marginBottom: '8px',
                      cursor: task.status === 'completed' ? 'pointer' : 'default',
                      color: task.status === 'completed' ? '#1890ff' : 'inherit'
                    }}
                    onClick={() => {
                      if (task.status === 'completed') {
                        // 找到对应的处理结果
                        // 这里需要根据任务ID找到对应的处理结果
                        // 由于我们没有存储任务ID和处理结果的对应关系，这里暂时不实现
                        message.info('点击了已完成的任务');
                      }
                    }}
                  >
                    {task.title.length > 20 ? task.title.substring(0, 20) + '...' : task.title}
                  </div>
                  <div style={{ fontSize: '12px', color: '#888', marginBottom: '8px' }}>
                    类别: {task.category}
                  </div>
                  <div style={{ fontSize: '12px', color: '#888' }}>
                    状态: 
                    {task.status === 'pending' && <span style={{ color: '#faad14' }}>等待中</span>}
                    {task.status === 'processing' && <span style={{ color: '#1890ff' }}>处理中</span>}
                    {task.status === 'completed' && <span style={{ color: '#52c41a' }}>已完成</span>}
                    {task.status === 'failed' && <span style={{ color: '#ff4d4f' }}>失败</span>}
                  </div>
                  {task.error && (
                    <div style={{ fontSize: '12px', color: '#ff4d4f', marginTop: '8px' }}>
                      错误: {task.error.substring(0, 50)}...
                    </div>
                  )}
                </Card>
              ))}
            </div>
          )}
        </Sider>
      </Layout>

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