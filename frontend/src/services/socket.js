/**
 * Single shared socket.io connection for the whole SPA.
 * In dev, Vite proxies /socket.io (ws) to Flask on :8080.
 */
import { io } from 'socket.io-client';

let socket = null;

export function getSocket() {
  if (!socket) {
    socket = io(window.location.origin, {
      transports: ['websocket', 'polling'],
      autoConnect: true,
    });
  }
  return socket;
}
