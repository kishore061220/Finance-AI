import axios from 'axios';

// Android Emulator
const API_BASE_URL = 'http://10.0.2.2:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export default api;