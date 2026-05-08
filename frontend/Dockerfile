# -- Etapa 1: Construcción (Build) --
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
# Compila la app para producción (crea la carpeta dist/)
RUN npm run build

# -- Etapa 2: Producción (Servidor Nginx) --
FROM nginx:alpine
# Copiamos solo los archivos estáticos del build anterior
COPY --from=build /app/dist /usr/share/nginx/html
# Copiar archivo de conf de Nginx si usas react-router (para que no de error 404 al recargar)
# Pero por defecto, Nginx sirve estáticos directo.
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]