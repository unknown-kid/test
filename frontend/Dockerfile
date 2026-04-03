FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN cp node_modules/pdfjs-dist/build/pdf.worker.min.mjs public/pdf.worker.js
RUN npm run build

FROM alpine:3.19
COPY --from=build /app/dist /app/dist
# Copy dist to the shared volume mount point on startup
CMD ["sh", "-c", "mkdir -p /out && cp -r /app/dist/* /out/"]
