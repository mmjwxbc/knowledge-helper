import React, { useState, useEffect } from 'react';
import { Layout, Upload, Input, Select, Button, Space, Card, Table, message, Modal, Form } from 'antd';
import { UploadOutlined, PlusOutlined, SendOutlined, CheckCircleOutlined, FolderOpenOutlined } from '@ant-design/icons';

const { Sider, Content } = Layout;
const API_BASE = 'http://localhost:8000/api';

const DataManagerPage = () => {
  const [categories, setCategories] = useState([]);
  const [currentResult, setCurrentResult] = useState(null);
  const [feedback, setFeedback] = useState('');
  const [finalItems, setFinalItems] = useState([]);
  const [status, setStatus] = useState('idle');
  const [url, setUrl] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('');
  const [addCategoryModal, setAddCategoryModal] = useState(false);
  const [selectedItems, setSelectedItems] = useState([]);
  const [form] = Form.useForm();

  // 获取数据库类别
  useEffect(() => {
    fetchCategories();
    fetchVaultData();
  }, []);

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
    try {
      const response = await fetch(`${API_BASE}/vault`);
      const data = await response.json();
      if (data.items) {
        setFinalItems(data.items);
      }
    } catch (error) {
      console.error('Failed to fetch vault data:', error);
    }
  };

  // 开始处理URL
  const handleStart = async () => {
    if (!url) {
      message.error('请输入URL地址');
      return;
    }

    setStatus('processing');
    try {
      const response = await fetch(`${API_BASE}/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, category: selectedCategory || '未分类' }),
      });

      const data = await response.json();
      if (data.error) {
        message.error(data.error);
        setStatus('idle');
      } else {
        setCurrentResult(data);
        setStatus('reviewing');
      }
    } catch (error) {
      message.error('处理失败，请检查网络连接');
      setStatus('idle');
    }
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

      // 逐个提交项目
      let successCount = 0;
      for (const index of indicesToSubmit) {
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

      if (successCount > 0) {
        message.success(`成功入库 ${successCount} 个项目`);
        await fetchVaultData();
        setStatus('finished');
        setCurrentResult(null);
        setSelectedItems([]);
      } else {
        message.error('入库失败');
      }
    } catch (error) {
      message.error('入库失败，请检查网络连接');
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
            loading={status === 'processing'}
          >
            {status === 'processing' ? '处理中...' : '开始处理'}
          </Button>

          <Button
            block
            size="large"
            icon={<FolderOpenOutlined />}
            onClick={() => setStatus('finished')}
          >
            查看知识库
          </Button>
        </Space>
      </Sider>

      <Content style={{ padding: '20px', background: '#fafafa', overflowY: 'auto' }}>
        {status === 'idle' && (
          <div style={{ textAlign: 'center', marginTop: '100px' }}>
            <p style={{ fontSize: '16px', color: '#888' }}>请在左侧输入URL以开始处理</p>
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

        {status === 'finished' && (
          <Card title="🎉 知识库内容" extra={<Button size="small" onClick={() => fetchVaultData()}>刷新</Button>}>
            <Table
              dataSource={finalItems}
              columns={[
                { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
                { title: '问题', dataIndex: 'question', key: 'question', ellipsis: true },
                { title: '类别', dataIndex: 'category', key: 'category', width: 120 },
                {
                  title: '入库时间',
                  dataIndex: 'created_at',
                  key: 'created_at',
                  width: 180,
                  render: (text) => new Date(text).toLocaleString('zh-CN'),
                },
              ]}
              pagination={{ pageSize: 10 }}
              rowKey="id"
            />
          </Card>
        )}
      </Content>

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