import type { CallingContext, CallingRegistration, BrowserCallTransport, RegistrationOptions, TransportState } from './definition';
import { LiveKitTransport } from '../conferencing/livekit';
import { createCarrierTransport, registerCarrier } from '../voip/calling';

interface Driver {
    /** Create a media session from this driver's implementation. */
    create(container: HTMLElement, onState: (state: TransportState) => void, context: CallingContext): BrowserCallTransport;
    /** Optionally subscribe to incoming calls for a provider-declared account. */
    register?(options: RegistrationOptions, context: CallingContext): Promise<CallingRegistration>;
}

/** Construct the room transport at the registered adapter boundary. */
function createLiveKit(container: HTMLElement, onState: (state: TransportState) => void, _context: CallingContext): BrowserCallTransport {
    return new LiveKitTransport(container, onState);
}
const drivers: Record<string, Driver> = {
    livekit: { create: createLiveKit },
    voip: { create: createCarrierTransport, register: registerCarrier },
};

/** Resolve only installed drivers named by an authorized provider response. */
function resolveDriver(driver: string): Driver {
    const selected = Object.prototype.hasOwnProperty.call(drivers, driver) ? drivers[driver] : undefined;
    if (!selected) throw new Error('Unsupported browser calling driver');
    return selected;
}

/** Construct a media session without assuming an IM provider or SDK. */
export function createBrowserCallTransport(driver: string, container: HTMLElement, onState: (state: TransportState) => void, context: CallingContext): BrowserCallTransport {
    return resolveDriver(driver).create(container, onState, context);
}

/** Subscribe through the registration capability declared by a driver. */
export async function registerCalling(options: RegistrationOptions, context: CallingContext): Promise<CallingRegistration> {
    const register = resolveDriver(options.driver).register;
    if (!register) throw new Error('This driver does not support incoming registrations');
    return await register(options, context);
}
