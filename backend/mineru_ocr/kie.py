# import asyncio
# from pathlib import Path
# from typing import Optional, Union

# import httpx

# class MinerUAgentAsyncClient:
#     def __init__(self, timeout: int = 60):
#         self.base_url = "https://mineru.net/api/v1/agent"
#         # 建议开启 follow_redirects=True，防止 OSS 域名重定向导致的问题
#         self.client = httpx.AsyncClient(
#             timeout=httpx.Timeout(timeout),
#             follow_redirects=True 
#         )

#     async def __aenter__(self):
#         return self

#     async def __aexit__(self, exc_type, exc_val, exc_tb):
#         await self.close()

#     async def close(self):
#         await self.client.aclose()

#     async def upload_and_parse_file(
#         self,
#         file_path: Union[str, Path],
#         language: str = "ch",
#         page_range: Optional[str] = None
#     ) -> str:
#         file_path = Path(file_path)
#         if not file_path.exists():
#             raise ValueError(f"文件不存在: {file_path}")

#         # 1. 获取签名上传 URL
#         endpoint = f"{self.base_url}/parse/file"
#         payload = {
#             "file_name": file_path.name,
#             "language": language
#         }
#         if page_range:
#             payload["page_range"] = page_range

#         # 必须 await
#         resp = await self.client.post(endpoint, json=payload)
#         resp.raise_for_status()
        
#         init_result = resp.json()
#         if init_result.get("code") != 0:
#             raise Exception(f"获取解析任务失败: {init_result.get('msg')}")

#         task_id = init_result["data"]["task_id"]
#         upload_url = init_result["data"]["file_url"]

#         # 2. 上传文件到 OSS
#         # 修复点：对于 10MB 以内的文件，直接读取 bytes 传递，避免 httpx 处理同步文件句柄报错
#         file_data = file_path.read_bytes()
        
#         # 必须 await，且使用 content 传递字节流
#         put_resp = await self.client.put(upload_url, content=file_data)
#         if put_resp.status_code not in (200, 201):
#             raise Exception(f"上传 OSS 失败: HTTP {put_resp.status_code}, {put_resp.text}")

#         return task_id

#     async def get_result(
#         self,
#         task_id: str,
#         timeout: int = 300,
#         poll_interval: int = 5
#     ) -> str:
#         result_url = f"{self.base_url}/parse/{task_id}"
#         start_time = asyncio.get_event_loop().time()

#         while True:
#             if (asyncio.get_event_loop().time() - start_time) > timeout:
#                 raise TimeoutError(f"解析轮询超时（{timeout}秒）")

#             # 必须 await
#             response = await self.client.get(result_url)
#             response.raise_for_status()
#             res_data = response.json()
            
#             if res_data.get("code") != 0:
#                 raise Exception(f"接口报错: {res_data.get('msg')}")

#             data = res_data.get("data", {})
#             state = data.get("state")

#             if state == "done":
#                 markdown_url = data.get("markdown_url")
#                 # 获取最终内容，必须 await
#                 md_content_resp = await self.client.get(markdown_url)
#                 md_content_resp.raise_for_status()
#                 return md_content_resp.text
            
#             elif state == "failed":
#                 raise Exception(f"解析失败: {data.get('err_msg', '未知错误')} (Code: {data.get('err_code')})")
            
#             else:
#                 # 状态为 waiting-file, uploading, pending, running 时继续等待
#                 await asyncio.sleep(poll_interval)


# # --- 使用示例 ---
# async def main():
#     async with MinerUAgentAsyncClient() as client:
#         try:
#             # 示例 1: 通过 URL 解析
#             # task_id = await client.parse_url("https://example.com/test.pdf")
            
#             # 示例 2: 通过本地文件上传解析
#             print("正在上传并创建任务...")
#             task_id = await client.upload_and_parse_file("demo.pdf")
#             print(f"任务 ID: {task_id}，开始轮询结果...")
            
#             # 轮询结果
#             markdown_text = await client.get_result(task_id)
#             print("--- 解析结果 ---")
#             print(markdown_text[:500] + "...") # 打印前500字
            
#         except Exception as e:
#             print(f"发生错误: {e}")

# if __name__ == "__main__":
#     asyncio.run(main())

import asyncio
from pathlib import Path
from typing import Optional, Union, List, Dict

import httpx

class MinerUAgentAsyncClient:
    def __init__(self, timeout: int = 60, max_concurrency: int = 3):
        self.base_url = "https://mineru.net/api/v1/agent"
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True 
        )
        # 为了防止触发 IP 限频（429），设置一个并发信号量
        self.semaphore = asyncio.Semaphore(max_concurrency)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        await self.client.aclose()

    async def upload_and_parse_file(
        self,
        file_path: Union[str, Path],
        language: str = "ch",
        page_range: Optional[str] = None
    ) -> str:
        """上传单个文件并返回 task_id"""
        file_path = Path(file_path)
        if not file_path.exists():
            raise ValueError(f"文件不存在: {file_path}")

        # 获取签名上传 URL
        endpoint = f"{self.base_url}/parse/file"
        payload = {"file_name": file_path.name, "language": language}
        if page_range:
            payload["page_range"] = page_range

        resp = await self.client.post(endpoint, json=payload)
        resp.raise_for_status()
        
        init_result = resp.json()
        if init_result.get("code") != 0:
            raise Exception(f"获取解析任务失败: {init_result.get('msg')}")

        task_id = init_result["data"]["task_id"]
        upload_url = init_result["data"]["file_url"]

        # 上传到 OSS
        file_data = file_path.read_bytes()
        put_resp = await self.client.put(upload_url, content=file_data)
        if put_resp.status_code not in (200, 201):
            raise Exception(f"上传 OSS 失败: HTTP {put_resp.status_code}")

        return task_id

    async def get_result(
        self,
        task_id: str,
        timeout: int = 300,
        poll_interval: int = 5
    ) -> str:
        """轮询单个任务的结果"""
        result_url = f"{self.base_url}/parse/{task_id}"
        start_time = asyncio.get_event_loop().time()

        while True:
            if (asyncio.get_event_loop().time() - start_time) > timeout:
                raise TimeoutError(f"解析轮询超时")

            response = await self.client.get(result_url)
            response.raise_for_status()
            res_data = response.json()
            
            if res_data.get("code") != 0:
                raise Exception(f"接口报错: {res_data.get('msg')}")

            data = res_data.get("data", {})
            state = data.get("state")

            if state == "done":
                markdown_url = data.get("markdown_url")
                md_content_resp = await self.client.get(markdown_url)
                md_content_resp.raise_for_status()
                return md_content_resp.text
            elif state == "failed":
                raise Exception(f"解析失败: {data.get('err_msg')}")
            else:
                await asyncio.sleep(poll_interval)

    async def process_one_file(self, file_path: str, **kwargs) -> tuple:
        """内部辅助方法：处理单个文件的完整生命周期（含并发控制）"""
        async with self.semaphore:
            try:
                task_id = await self.upload_and_parse_file(file_path, **kwargs)
                result = await self.get_result(task_id)
                return file_path, result, None
            except Exception as e:
                return file_path, None, str(e)

    async def batch_parse_files(self, file_paths: List[str], **kwargs) -> Dict[str, Dict]:
        """
        批量解析文件
        返回格式: { "file_a.pdf": {"content": "...", "error": None}, ... }
        """
        tasks = [self.process_one_file(fp, **kwargs) for fp in file_paths]
        # 并发执行所有任务
        finished_tasks = await asyncio.gather(*tasks)
        
        results = {}
        for fp, content, error in finished_tasks:
            results[fp] = {"content": content, "error": error}
        return results

# --- 使用示例 ---
async def main():
    file_list = ["demo1.pdf", "demo2.png", "demo3.docx"]
    
    # max_concurrency 建议不要设太大，防止被接口限频（429）
    async with MinerUAgentAsyncClient(max_concurrency=2) as client:
        print(f"开始批量解析 {len(file_list)} 个文件...")
        
        batch_results = await client.batch_parse_files(file_list, language="ch")
        
        for file_path, res in batch_results.items():
            if res["error"]:
                print(f"❌ {file_path} 处理失败: {res['error']}")
            else:
                print(f"✅ {file_path} 解析成功，长度: {len(res['content'])}")

if __name__ == "__main__":
    asyncio.run(main())