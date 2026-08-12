# 1. Specify the base image (like choosing a shell for the project)
FROM python:3.9-slim

# 2. Set the working directory inside the container
WORKDIR /app

# 3. Copy the dependency list into the container
COPY requirements.txt .

# 4. Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the remaining code and HTML files
COPY . .

# 6. Expose the port that the container will use
EXPOSE 8000

# 7. Start the app when the container launches
CMD ["uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "8000"]