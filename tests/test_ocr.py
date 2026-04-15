import asyncio
# 假设你的新客户端保存在 backend/mineru_agent.py 中
from backend.mineru_ocr import MinerUAgentAsyncClient

async def test_agent_ocr():
    # 1. 初始化客户端 (Base URL 已在内部固定)
    client = MinerUAgentAsyncClient(timeout=30)

    task_id = None
    file_paths = ["image.png", "屏幕截图 2025-05-26 155723.png"]

    try:
        # 2. 上传并创建任务
        # 该方法内部包含了：获取签名 URL -> PUT 上传文件 -> 返回 task_id
        print(f"🚀 正在上传文件: {file_paths} ...")
        batch_results = await client.batch_parse_files(file_paths, language="ch")
        print(f"✅ 批量处理完成，共处理 {len(batch_results)}")
        
        for file_path, res in batch_results.items():
            if res["error"]:
                print(f"❌ {file_path} 处理失败: {res['error']}")
            else:
                print(f"✅ {file_path} 解析成功，内容: {res['content']}")
    except ValueError as e:
        print(f"❌ 参数或文件错误: {e}")
        return
    except Exception as e:
        print(f"❌ 上传阶段失败: {e}")
        return
    
    finally:
        # 记得关闭客户端连接池
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_agent_ocr())