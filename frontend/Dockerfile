# Frontend dev image (TASK-003, EPIC-01).
# Dev-only: runs the Vite dev server with hot reload. The compose `frontend`
# service bind-mounts ./frontend over /app (with an anonymous volume for
# node_modules), so the image just needs the toolchain + installed deps.
# A production build stage (vite build → static serve) is added later if needed.
FROM node:20-alpine

WORKDIR /app

# Install deps first for layer caching; package*.json change → reinstall only.
COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 5173

# --host so the server is reachable from outside the container.
CMD ["npm", "run", "dev"]
