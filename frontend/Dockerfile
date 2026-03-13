FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "3000"]
