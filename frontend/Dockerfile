# Build the dashboard, then serve the static files with nginx.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# The browser calls the API directly, so this is the API address as seen from the user's machine.
ARG VITE_BACKEND_URL=http://localhost:8000
ENV VITE_BACKEND_URL=$VITE_BACKEND_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Security headers and a Content-Security-Policy that only allows the dashboard's own API.
# The nginx image fills ${API_ORIGIN} in the template when the container starts.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ARG VITE_BACKEND_URL=http://localhost:8000
ENV API_ORIGIN=$VITE_BACKEND_URL
EXPOSE 80
