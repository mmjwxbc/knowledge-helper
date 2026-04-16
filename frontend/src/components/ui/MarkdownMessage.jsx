import { useState } from 'react';
import { Button, Space, Tooltip, message } from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import Prism from 'prismjs';
import 'prismjs/components/prism-bash';
import 'prismjs/components/prism-javascript';
import 'prismjs/components/prism-jsx';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-markdown';
import 'prismjs/components/prism-python';
import 'prismjs/themes/prism-tomorrow.css';
import { cx } from '../../lib/classNames';

const COLLAPSED_CODE_HEIGHT = 260;

const getCodeLanguage = (className = '') => {
  const match = /language-([\w-]+)/.exec(className);
  return match?.[1]?.toLowerCase() || 'text';
};

const getHighlightedCode = (code, language) => {
  const normalizedLanguage =
    language === 'sh' || language === 'shell' ? 'bash' : language === 'py' ? 'python' : language;
  const grammar = Prism.languages[normalizedLanguage];
  return grammar
    ? Prism.highlight(code, grammar, normalizedLanguage)
    : code.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
};

function CodeBlock({ className, inline, children, ...props }) {
  const rawCode = String(children).replace(/\n$/, '');
  const language = getCodeLanguage(className);
  const lineCount = rawCode.split('\n').length;
  const collapsible = lineCount > 12 || rawCode.length > 520;
  const [expanded, setExpanded] = useState(!collapsible);

  if (inline) {
    return (
      <code className="inline-code" {...props}>
        {children}
      </code>
    );
  }

  const highlightedCode = getHighlightedCode(rawCode, language);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(rawCode);
      message.success('代码已复制');
    } catch {
      message.error('复制失败');
    }
  };

  return (
    <div className="code-block-shell">
      <div className="code-block-toolbar">
        <span className="code-language">{language}</span>
        <Space size={8}>
          {collapsible ? (
            <Button size="small" type="text" onClick={() => setExpanded((value) => !value)}>
              {expanded ? '收起' : '展开'}
            </Button>
          ) : null}
          <Tooltip title="复制代码">
            <Button size="small" type="text" icon={<CopyOutlined />} onClick={handleCopy} />
          </Tooltip>
        </Space>
      </div>
      <div
        className={cx('code-block-body', !expanded && 'code-block-collapsed')}
        style={!expanded ? { maxHeight: COLLAPSED_CODE_HEIGHT } : undefined}
      >
        <pre className={cx(className, 'code-block-pre')}>
          <code dangerouslySetInnerHTML={{ __html: highlightedCode }} {...props} />
        </pre>
      </div>
    </div>
  );
}

export default function MarkdownMessage({ content }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const inline = !className && !String(children).includes('\n');
            return (
              <CodeBlock className={className} inline={inline} {...props}>
                {children}
              </CodeBlock>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
