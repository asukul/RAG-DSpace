# Build stage
FROM node:22-alpine as build

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build arguments — baked into the JS bundle at build time
ARG VITE_API_URL
ARG VITE_GOOGLE_OAUTH_CLIENT_ID
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_GOOGLE_OAUTH_CLIENT_ID=$VITE_GOOGLE_OAUTH_CLIENT_ID

# Build the application
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy built assets
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx config as a template — entrypoint envsubst expands ${PORT}
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Cloud Run injects PORT (8080); local docker-compose can override
ENV PORT=80
EXPOSE 80

# nginx:alpine entrypoint runs envsubst on /etc/nginx/templates/*.template
# automatically and writes the result to /etc/nginx/conf.d/.
CMD ["nginx", "-g", "daemon off;"]
