/** Play distinct incoming chimes and outgoing ringback through the owner tab's audio. */
export default class CallRingtone {
    private context: AudioContext | null = null;
    private buffer: AudioBuffer | null = null;
    private ringbackBuffer: AudioBuffer | null = null;
    private source: AudioBufferSourceNode | null = null;
    private playing: 'incoming' | 'outgoing' | null = null;
    private ringing = false;
    private ringback = false;
    private enabled = false;
    private previewing = false;
    private previewTimer: number | null = null;
    private muted = false;
    private disposed = false;

    /** Report autoplay restrictions so the panel can offer an explicit sound control. */
    public constructor(private readonly blocked: (blocked: boolean) => void) {}

    /** Check sound readiness before a call arrives, without capturing microphone audio. */
    public setEnabled(enabled: boolean): void {
        this.enabled = enabled;
        if (enabled) this.unlock();
        else {
            this.ringing = false;
            this.clearPreview();
        }
        this.sync();
    }

    /** Resume playback from a user gesture, including browsers reporting interrupted audio. */
    public unlock(): void {
        if (this.disposed || !window.AudioContext) return;
        if (!this.context || this.context.state === 'closed') {
            this.context = new AudioContext();
            this.buffer = null;
            this.ringbackBuffer = null;
        }
        this.context.onstatechange = this.sync;
        if (this.context.state !== 'running') void this.context.resume().then(this.sync, this.unavailable);
        this.sync();
    }

    /** Play a short receiving-ringtone preview from the explicit sound control. */
    public preview(): void {
        if (this.disposed || this.muted && !this.ringback) return;
        this.unlock();
        if (this.ringing || this.ringback) return;
        this.clearPreview();
        this.previewing = true;
        this.previewTimer = window.setTimeout(this.endPreview, 3200);
        this.sync();
    }

    /** Expire the preview without affecting an invitation that starts in the meantime. */
    private endPreview = (): void => { this.previewTimer = null; this.previewing = false; this.sync(); };

    /** Cancel pending preview audio before a call starts, ends or changes ownership. */
    private clearPreview(): void {
        if (this.previewTimer !== null) window.clearTimeout(this.previewTimer);
        this.previewTimer = null;
        this.previewing = false;
    }

    /** Apply the remembered sound preference while retaining visual call alerts. */
    public setMuted(muted: boolean): void {
        this.muted = muted;
        this.sync();
    }

    /** Start or stop ringing immediately as an invitation changes state. */
    public setRinging(ringing: boolean): void {
        this.clearPreview();
        this.ringing = ringing;
        if (ringing) this.unlock();
        this.sync();
    }

    /** Play caller feedback independently of the incoming-call and incoming-mute preferences. */
    public setRingback(ringing: boolean): void {
        if (this.ringback === ringing) return;
        this.ringback = ringing;
        if (ringing) {
            this.clearPreview();
            this.unlock();
        }
        this.sync();
    }

    /** Keep a looping audio buffer independent of background-tab timer throttling. */
    private sync = (): void => {
        if (this.disposed) return;
        const mode = this.ringback ? 'outgoing' : (this.ringing || this.previewing) && !this.muted ? 'incoming' : null;
        if (mode !== this.playing || !mode || this.context?.state !== 'running') {
            this.source?.stop();
            this.source?.disconnect();
            this.source = null;
            this.playing = null;
        }
        if (!mode || this.context?.state !== 'running') {
            this.blocked((this.ringback || this.enabled && !this.muted) && this.context?.state !== 'running');
            return;
        }
        this.blocked(false);
        if (this.source) return;
        this.source = this.context.createBufferSource();
        if (mode === 'outgoing') {
            this.ringbackBuffer ??= this.createRingbackBuffer(this.context);
            this.source.buffer = this.ringbackBuffer;
        } else {
            this.buffer ??= this.createIncomingBuffer(this.context);
            this.source.buffer = this.buffer;
        }
        this.playing = mode;
        this.source.loop = true;
        this.source.connect(this.context.destination);
        this.source.start();
    };

    /** Generate a low, rounded double pulse with a pause, distinct from receiving chimes. */
    private createRingbackBuffer(context: AudioContext): AudioBuffer {
        const rate = context.sampleRate;
        const buffer = context.createBuffer(1, Math.ceil(rate * 4), rate);
        const samples = buffer.getChannelData(0);
        const duration = .55;
        for (const start of [0, .8]) {
            const offset = Math.round(start * rate);
            for (let index = 0; index < Math.floor(duration * rate); index++) {
                const time = index / rate;
                const envelope = Math.min(1, time / .015, (duration - time) / .025);
                samples[offset + index] = .12 * envelope * (Math.sin(2 * Math.PI * 425 * time) + .22 * Math.sin(2 * Math.PI * 450 * time));
            }
        }
        return buffer;
    }

    /** Compose two warm chime phrases over a soft harmony, followed by a quiet pause. */
    private createIncomingBuffer(context: AudioContext): AudioBuffer {
        const rate = context.sampleRate;
        const buffer = context.createBuffer(2, Math.ceil(rate * 4.2), rate);
        const left = buffer.getChannelData(0);
        const right = buffer.getChannelData(1);
        const notes: readonly (readonly [number, number, number, number])[] = [
            [0, 587.33, -.18, 1], [.18, 739.99, .12, .85],
            [.38, 880, -.08, .9], [.62, 1174.66, .18, .75],
            [1.05, 880, .15, .9], [1.23, 739.99, -.12, .8],
            [1.43, 659.25, .08, .75], [1.67, 587.33, -.08, .95],
        ];
        for (const [start, frequency, pan, strength] of notes) this.addChime(left, right, rate, start, frequency, pan, strength);
        for (let index = 0; index < Math.floor(rate * 2.3); index++) {
            const time = index / rate;
            const envelope = Math.min(1, time / .08, (2.3 - time) / .55) * Math.exp(-time / 1.2);
            const harmony = .018 * envelope * (Math.sin(2 * Math.PI * 293.66 * time) + .55 * Math.sin(2 * Math.PI * 440 * time));
            left[index] += harmony;
            right[index] += harmony;
        }
        this.addAmbience(left, right, rate);
        let peak = .28;
        for (let index = 0; index < left.length; index++) peak = Math.max(peak, Math.abs(left[index]), Math.abs(right[index]));
        const gain = .28 / peak;
        for (let index = 0; index < left.length; index++) {
            left[index] *= gain;
            right[index] *= gain;
        }
        return buffer;
    }

    /** Layer rounded bell harmonics, a quiet lower octave and gentle stereo positioning. */
    private addChime(left: Float32Array, right: Float32Array, rate: number, start: number, frequency: number, pan: number, strength: number): void {
        const offset = Math.round(start * rate);
        const duration = .9;
        const leftGain = Math.sqrt((1 - pan) / 2);
        const rightGain = Math.sqrt((1 + pan) / 2);
        for (let index = 0; index < Math.floor(duration * rate); index++) {
            const time = index / rate;
            const phase = 2 * Math.PI * frequency * time;
            const envelope = (1 - Math.exp(-time / .009)) * Math.min(1, (duration - time) / .08);
            const fundamental = (Math.sin(phase) + .25 * Math.sin(phase * 1.002)) * Math.exp(-time / .3);
            const bell = .22 * Math.sin(phase * 2) * Math.exp(-time / .17) + .07 * Math.sin(phase * 3) * Math.exp(-time / .1);
            const warmth = .2 * Math.sin(phase / 2) * Math.exp(-time / .36);
            const sample = .16 * strength * envelope * (fundamental + bell + warmth);
            left[offset + index] += sample * leftGain;
            right[offset + index] += sample * rightGain;
        }
    }

    /** Add subtle, fading stereo reflections while keeping the next ringing cycle clean. */
    private addAmbience(left: Float32Array, right: Float32Array, rate: number): void {
        const dryLeft = left.slice();
        const dryRight = right.slice();
        const reflections: readonly (readonly [number, number])[] = [[.09, .16], [.17, .1], [.29, .06], [.43, .035]];
        for (const [delay, gain] of reflections) {
            const offset = Math.round(delay * rate);
            for (let index = offset; index < left.length; index++) {
                left[index] += dryRight[index - offset] * gain;
                right[index] += dryLeft[index - offset] * gain;
            }
        }
    }

    /** Keep blocked sound recoverable even when no incoming call is currently ringing. */
    private unavailable = (): void => { if (!this.disposed) this.blocked(this.ringback || this.enabled && !this.muted); };

    /** Release audio resources when the application shell actually unloads. */
    public destroy(): void {
        this.enabled = false;
        this.ringing = false;
        this.ringback = false;
        this.clearPreview();
        this.sync();
        this.disposed = true;
        if (this.context) {
            this.context.onstatechange = null;
            void this.context.close().catch(this.unavailable);
        }
        this.context = null;
        this.buffer = null;
        this.ringbackBuffer = null;
    }
}
