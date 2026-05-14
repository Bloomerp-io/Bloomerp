import { getComponent } from "@/components/BaseComponent"
import { Modal } from "@/components/Modal"


export default function getGeneralModal(): Modal {
    const modal = getModal("bloomerp-general-use-modal")
    modal.resetToDefaults()
    return modal
}

/**
 * Returns a modal
 * @param id the modal id
 */
export function getModal(id:string) : Modal {
    return getComponent(document.getElementById(id)) as Modal
}

/**
 * Opens a modal with the given ID.
 * @param modalId The ID of the modal to open.
 * @returns void
 */
export function openModal(modalId: string): void {
    const modalEl = document.getElementById(modalId);
    if (!modalEl) {
        console.error(`No modal found with ID: ${modalId}`);
        return;
    }

    const modal = getComponent(modalEl) as Modal | null;
    if (!modal) {
        console.error(`Element with ID ${modalId} is not a Modal component:`, modalEl);
        return;
    }

    modal.open();
}


/**
 * Closes a modal with the given ID.
 * @param modalId The ID of the modal to close.
 * @returns void
 */
export function closeModal(modalId: string): void {
    const modalEl = document.getElementById(modalId);
    if (!modalEl) {
        console.error(`No modal found with ID: ${modalId}`);
        return;
    }

    const modal = getComponent(modalEl) as Modal | null;
    if (!modal) {
        console.error(`Element with ID ${modalId} is not a Modal component:`, modalEl);
        return;
    }

    modal.close();
}
