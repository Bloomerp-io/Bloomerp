/**
 * Messages module for Bloomerp application.
 */
import showMessage from '../utils/messages';
import { MessageType } from '../components/UiMessage';

type ToastPayload = {
    type?: string;
    message?: string;
    level?: string;
    duration?: number;
};

const coerceMessageType = (value?: string): MessageType => {
    switch ((value || '').toLowerCase()) {
        case 'success':
            return MessageType.SUCCESS;
        case 'warning':
        case 'warn':
            return MessageType.WARNING;
        case 'error':
            return MessageType.ERROR;
        case 'info':
        default:
            return MessageType.INFO;
    }
};

const handleToast = (payload: ToastPayload): void => {
    const message = payload.message;
    if (!message) {
        return;
    }

    const messageType = coerceMessageType(payload.level ?? payload.type);
    const duration = payload.duration ?? 5;

    showMessage(message, messageType, duration);
};

export const initMessagesWebsocket = (): void => {
    if (typeof window === 'undefined') {
        return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${protocol}://${window.location.host}/ws/notifications/`;

    const socket = new WebSocket(wsUrl);

    socket.onmessage = (event: MessageEvent<string>): void => {
        try {
            const data = JSON.parse(event.data) as ToastPayload;
            if (data.type === 'toast' || data.message) {
                handleToast(data);
            }
        } catch (error) {
            console.warn('Failed to parse websocket message', error);
        }
    };

    socket.onerror = (event): void => {
        console.warn('Websocket error', event);
    };
};
