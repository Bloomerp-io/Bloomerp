import { Room, RoomEvent, Track, LocalVideoTrack, type RemoteTrack, type RemoteTrackPublication, type RemoteParticipant, type LocalTrackPublication, type LocalParticipant } from 'livekit-client';
import type { CallCredentials, CallParticipant, BrowserCallTransport, TransportState } from '../calling/definition';

/** Adapt LiveKit tracks and lifecycle to the shared conferencing controls. */
export class LiveKitTransport implements BrowserCallTransport {
    // Video is mirrored into a presentation tab; hidden owner elements must not pause subscriptions.
    private room = new Room({ adaptiveStream: false, dynacast: true });
    private disposed = false;

    /** Bind SDK events before connecting so early tracks are never missed. */
    public constructor(private container: HTMLElement, private onState: (state: TransportState) => void) {
        this.room.on(RoomEvent.TrackSubscribed, this.subscribed);
        this.room.on(RoomEvent.TrackUnsubscribed, this.detached);
        this.room.on(RoomEvent.LocalTrackPublished, this.localPublished);
        this.room.on(RoomEvent.LocalTrackUnpublished, this.localUnpublished);
        this.room.on(RoomEvent.Reconnecting, this.reconnecting);
        this.room.on(RoomEvent.Reconnected, this.connected);
        this.room.on(RoomEvent.Disconnected, this.disconnected);
    }

    /** Connect only; capture is enabled separately by the initiating gesture. */
    public async connect(credentials: CallCredentials): Promise<void> {
        await this.room.connect(credentials.url, credentials.token);
        if (this.disposed) { await this.room.disconnect(); return; }
        this.connected();
    }

    /** Normalize SDK membership and server-issued IM identities for the shared call view. */
    public participants(): CallParticipant[] {
        return [this.room.localParticipant, ...this.room.remoteParticipants.values()].map((person: LocalParticipant | RemoteParticipant): CallParticipant => {
            let identity: Record<string, unknown> = {};
            try { identity = JSON.parse(person.metadata || '{}'); } catch { /* Older rooms have no presentation metadata. */ }
            if (!identity || typeof identity !== 'object') identity = {};
            const camera = person.getTrackPublication(Track.Source.Camera);
            const video = camera && !camera.isMuted ? Array.from(this.container.querySelectorAll<HTMLVideoElement>('video')).find((element: HTMLVideoElement): boolean => element.dataset.participant === person.identity && element.dataset.source === Track.Source.Camera) : undefined;
            return {
                id: person.identity || 'local',
                displayName: typeof identity.displayName === 'string' ? identity.displayName : person.name || person.identity,
                avatar: typeof identity.avatar === 'string' ? identity.avatar : '',
                initials: typeof identity.initials === 'string' ? identity.initials : '',
                local: person === this.room.localParticipant,
                video,
                screenVideo: person.isScreenShareEnabled ? Array.from(this.container.querySelectorAll<HTMLVideoElement>('video')).find((element: HTMLVideoElement): boolean => element.dataset.participant === person.identity && element.dataset.source === Track.Source.ScreenShare) : undefined,
            };
        });
    }

    /** Stop capture and detach every rendered media element. */
    public async disconnect(): Promise<void> {
        this.disposed = true;
        await this.room.disconnect(true);
        this.room.removeAllListeners();
        this.container.replaceChildren();
    }

    /** Toggle local microphone publication. */
    public async microphone(enabled: boolean): Promise<void> {
        if (this.disposed) return;
        await this.room.localParticipant.setMicrophoneEnabled(enabled);
        if (this.disposed) await this.room.disconnect(true);
    }

    /** Toggle camera capture and local preview. */
    public async camera(enabled: boolean): Promise<void> {
        if (this.disposed) return;
        await this.room.localParticipant.setCameraEnabled(enabled);
        if (this.disposed) await this.room.disconnect(true);
    }

    /** Publish capture from the initiating tab without opening a second browser chooser. */
    public async screenShare(enabled: boolean, stream?: MediaStream): Promise<void> {
        if (!enabled) {
            await this.room.localParticipant.setScreenShareEnabled(false);
            return;
        }
        const video = stream?.getVideoTracks()[0];
        if (!video || video.readyState !== 'live' || this.disposed) {
            for (const track of stream?.getTracks() || []) track.stop();
            if (!this.disposed) throw new Error('Screen capture is no longer available.');
            return;
        }
        try {
            // The raw track may belong to another Window and fail SDK instanceof checks.
            const track = new LocalVideoTrack(video, undefined, true);
            track.source = Track.Source.ScreenShare;
            await this.room.localParticipant.publishTrack(track, { source: Track.Source.ScreenShare });
            if (this.disposed) await this.room.disconnect(true);
        } catch (error: unknown) {
            for (const track of stream!.getTracks()) track.stop();
            throw error;
        }
    }

    /** Reflect SDK state after browser-native stop-sharing actions. */
    public screenSharing(): boolean { return !this.disposed && this.room.localParticipant.isScreenShareEnabled; }

    /** Resume subscribed audio following an explicit browser gesture. */
    public async playAudio(): Promise<void> { await this.room.startAudio(); }

    /** Render each remote track with the participant's display name. */
    private subscribed = (track: RemoteTrack, _publication: RemoteTrackPublication, participant: RemoteParticipant): void => {
        this.attach(track, participant.name || participant.identity, false, participant.identity);
    };

    /** Render only local video to prevent microphone feedback. */
    private localPublished = (publication: LocalTrackPublication, participant: LocalParticipant): void => {
        if (publication.track?.kind === Track.Kind.Video) this.attach(publication.track, participant.name || '', true, participant.identity);
    };

    /** Remove a local preview when its publication ends. */
    private localUnpublished = (publication: LocalTrackPublication): void => {
        if (publication.track) this.detached(publication.track);
    };

    /** Attach SDK media without inserting participant names as HTML. */
    private attach(track: Track, name: string, local: boolean, identity: string): void {
        const media = track.attach();
        media.dataset.participant = identity;
        media.dataset.source = track.source;
        media.autoplay = true;
        media.muted = local;
        media.setAttribute('aria-label', name);
        if (media instanceof HTMLVideoElement) {
            media.playsInline = true;
            media.style.width = '100%';
            media.style.maxHeight = '240px';
        }
        this.container.append(media);
    }

    /** Remove detached tracks from the persistent media container. */
    private detached = (track: Track): void => {
        for (const element of track.detach()) element.remove();
    };

    /** Report recovered connectivity through the normalized lifecycle. */
    private connected = (): void => { if (!this.disposed) this.onState('connected'); };
    /** Keep controls visible during automatic SDK reconnection. */
    private reconnecting = (): void => { if (!this.disposed) this.onState('reconnecting'); };
    /** Notify the shell of remote termination or unrecoverable disconnection. */
    private disconnected = (): void => { if (!this.disposed) this.onState('disconnected'); };
}
