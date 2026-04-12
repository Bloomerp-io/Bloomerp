/**
 * Tailwind CSS v4 configuration
 * 
 * For Tailwind CSS v4, most configuration is now handled in the CSS file itself
 * using the new @theme and @layer directives. This config file is simplified.
 */

module.exports = {
    content: [
        /**
         * HTML. Paths to Django template files that will contain Tailwind CSS classes.
         */

        /*  Templates within theme app (<tailwind_app_name>/templates), e.g. base.html. */
        '../templates/**/*.html',

        /*
         * Main templates directory of the project (BASE_DIR/templates).
         * Adjust the following line to match your project structure.
         */
        '../../templates/**/*.html',

        /*
         * Templates in other django apps (BASE_DIR/<any_app_name>/templates).
         * Adjust the following line to match your project structure.
         */
        '../../**/templates/**/*.html',

        /**
         * JS: If you use Tailwind CSS in JavaScript, uncomment the following lines and make sure
         * patterns match your project structure.
         */
        /* JS 1: Ignore any JavaScript in node_modules folder. */
        // '!../../**/node_modules',
        /* JS 2: Process all JavaScript files in the project. */
        // '../../**/*.js',

        /**
         * Python: If you use Tailwind CSS classes in Python, uncomment the following line
         * and make sure the pattern below matches your project structure.
         */
        // '../../**/*.py'
    ],
    safelist: [
        'bg-[#000000]/4',
        'bg-[#000000]/6',
        'text-[#000000]',
        'bg-[#FF4D4F]/4',
        'bg-[#FF4D4F]/6',
        'text-[#FF4D4F]',
        'bg-[#FF6A21]/4',
        'bg-[#FF6A21]/6',
        'text-[#FF6A21]',
        'bg-[#F4B400]/4',
        'bg-[#F4B400]/6',
        'text-[#F4B400]',
        'bg-[#12C152]/4',
        'bg-[#12C152]/6',
        'text-[#12C152]',
        'bg-[#2383EB]/4',
        'bg-[#2383EB]/6',
        'text-[#2383EB]',
        'bg-[#4F46E5]/4',
        'bg-[#4F46E5]/6',
        'text-[#4F46E5]',
        'bg-[#8B5CF6]/4',
        'bg-[#8B5CF6]/6',
        'text-[#8B5CF6]',
        'bg-[#F35BA5]/4',
        'bg-[#F35BA5]/6',
        'text-[#F35BA5]',
        'bg-[#14B8A6]/4',
        'bg-[#14B8A6]/6',
        'text-[#14B8A6]',
        'bg-[#A855F7]/4',
        'bg-[#A855F7]/6',
        'text-[#A855F7]',
        'bg-[#64748B]/4',
        'bg-[#64748B]/6',
        'text-[#64748B]',
        'ring-2',
        'ring-gray-900',
        'ring-offset-2',
        'scale-[1.03]',
    ],
}