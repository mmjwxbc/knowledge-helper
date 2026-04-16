export const readSseStream = async (response, onMessage) => {
  if (!response.body) {
    throw new Error('流式响应不可用');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const flushEvent = async (rawEvent) => {
    const dataLines = rawEvent
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim());

    if (dataLines.length === 0) return false;

    const payload = dataLines.join('\n');
    if (!payload || payload === '[DONE]') {
      return payload === '[DONE]';
    }

    try {
      await onMessage(JSON.parse(payload));
    } catch (error) {
      console.error('Error parsing SSE data:', error);
    }
    return false;
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split('\n\n');
    buffer = events.pop() || '';

    for (const event of events) {
      const shouldStop = await flushEvent(event);
      if (shouldStop) return;
    }
  }

  if (buffer.trim()) {
    await flushEvent(buffer);
  }
};
