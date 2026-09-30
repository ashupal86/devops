# ============================================================
# STAGE 1: Build frontend
# ============================================================

FROM node:20-alpine AS builder

WORKDIR /app

# Copy dependency files first.
# This allows Docker to cache npm ci when source code changes.
COPY package.json package-lock.json ./

RUN npm ci

# Copy source files.
COPY tsconfig.json vite.config.ts index.html ./
COPY src/ ./src

# Build production assets.
RUN npm run build


# ============================================================
# STAGE 2: Nginx production server
# ============================================================

FROM nginx:1.25-alpine AS runner

# Remove default Nginx content.
RUN rm -rf /usr/share/nginx/html/*

# Copy React/Vite production build.
COPY --from=builder /app/dist /usr/share/nginx/html

# Replace default Nginx configuration.
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
