# 1. 指定基础镜像（就像选个毛坯房，这里选个带 Python 的精装修房）
FROM python:3.9-slim

# 2. 设置工作目录（进入容器后的默认操作文件夹）
WORKDIR /app

# 3. 复制依赖清单到容器里
COPY requirements.txt .

# 4. 执行安装命令（让机器人帮你装好所有插件）
RUN pip install --no-cache-dir -r requirements.txt

# 5. 复制剩下的所有代码和 HTML 文件
COPY . .

# 6. 告诉容器要对外开放哪个端口
EXPOSE 8000

# 7. 启动命令（容器一启动就执行这条，保持程序运行）
CMD ["uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "8000"]