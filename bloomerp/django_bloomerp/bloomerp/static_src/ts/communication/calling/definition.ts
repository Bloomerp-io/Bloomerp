/** Provider-resolved identity and optional owner-tab video for one connected participant. */
export interface CallParticipant {
    id: string;
    displayName: string;
    avatar?: string;
    initials?: string;
    local?: boolean;
    video?: HTMLVideoElement;
    screenVideo?: HTMLVideoElement;
}

/** Authorized browser contract returned by a provider's join endpoint. */
export interface CallCredentials {
    session_id: string;
    join_url: string;
    end_url: string;
    media_mode: string;
    driver: string;
    url: string;
    token: string;
    can_video: string;
    can_screen_share?: string;
    can_end: string;
    share_url?: string;
    admissions_url?: string;
    cancel_url?: string;
    call_id?: string;
    registration_id?: string;
    token_url?: string;
    carrier_driver?: string;
    participants?: CallParticipant[];
}

/** Media lifecycle independent of the IM provider and its underlying SDK. */
export interface BrowserCallTransport {
    /** Connect after explicit user consent without retaining credentials. */
    connect(credentials: CallCredentials): Promise<void>;
    /** Bind lifecycle delivery when a driver offers an incoming transport. */
    setStateListener?(listener: (state: TransportState) => void): void;
    /** Return connected participants, including those whose cameras are off. */
    participants?(): CallParticipant[];
    /** Release all local capture and remote media. */
    disconnect(): Promise<void>;
    /** Enable or disable microphone publication. */
    microphone(enabled: boolean): Promise<void>;
    /** Enable or disable camera publication. */
    camera(enabled: boolean): Promise<void>;
    /** Publish a browser-selected screen stream, or stop the current publication. */
    screenShare?(enabled: boolean, stream?: MediaStream): Promise<void>;
    /** Report capture state, including stopping through browser controls. */
    screenSharing?(): boolean;
    /** Resume audio playback after a browser blocks autoplay. */
    playAudio(): Promise<void>;
}

/** Report SDK state using application-owned labels. */
export type TransportState = 'connected' | 'reconnecting' | 'disconnected';

/** Incoming media is supplied by the driver, never by a UI provider branch. */
export interface IncomingCall {
    credentials: CallCredentials;
    transport: BrowserCallTransport;
}

/** Shared server requests and invitation delivery supplied to media adapters. */
export interface CallingContext {
    /** Make a same-origin authorized provider request. */
    post<T>(url: string, body?: URLSearchParams): Promise<T>;
    /** Offer a driver-owned incoming session without accepting it. */
    incoming(call: IncomingCall): void;
    /** Surface a registration failure without leaking transport details. */
    registrationError(): void;
    /** Transfer ownership of a registration to the persistent application shell. */
    registrationCreated(registration: CallingRegistration): void;
}

/** Persistent incoming registration lifetime, independent of an active call. */
export interface CallingRegistration {
    /** Release credentials, incoming subscriptions and active SDK resources. */
    destroy(): void;
}

/** Server-declared incoming endpoint consumed uniformly by the browser shell. */
export interface RegistrationOptions { id: string; driver: string; token_url: string }

/** Browser operations that must run in the document receiving the user's click. */
export interface CallActionContext {
    /** Open this document's screen chooser with live user activation. */
    capture?(): Promise<MediaStream>;
    /** Copy the authorized meeting URL using this document's clipboard permission. */
    copy?(text: string): Promise<void>;
}
