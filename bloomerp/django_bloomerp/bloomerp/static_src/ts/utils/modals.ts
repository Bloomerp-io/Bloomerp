import { getComponent } from "@/components/BaseComponent"
import { Modal } from "@/components/Modal"


export default function getGeneralModal(): Modal {
    return getComponent(document.getElementById("bloomerp-general-use-modal")) as Modal
}