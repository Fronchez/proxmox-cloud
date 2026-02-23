import axios from "axios";

// Используем относительный путь для API
// Запросы будут идти на тот же домен, где размещен frontend
const API_URL = "/api";

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

// Интерцептор для JWT токена
export const setToken = (token) => {
  api.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  localStorage.setItem("token", token);
};

export const removeToken = () => {
  delete api.defaults.headers.common["Authorization"];
  localStorage.removeItem("token");
};

// Интерцептор для обработки ошибок
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      removeToken();
      window.location.href = "/";
    }
    return Promise.reject(error);
  }
);
