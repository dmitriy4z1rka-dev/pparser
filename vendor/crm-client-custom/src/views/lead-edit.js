define('custom:views/lead-edit', ['views/record/edit'], function (EditRecordView) {
    return class extends EditRecordView {
        events = Object.assign({}, super.events, {
            'keydown .field input, .field textarea, .field select': function (event) {
                if (event.key !== 'Enter') return;
                const target = event.target;
                if (target.tagName === 'TEXTAREA' && event.shiftKey) return;
                if (target.tagName === 'INPUT' && ['button', 'submit', 'checkbox', 'radio'].includes(target.type)) return;
                event.preventDefault();
                event.stopPropagation();
                this.actionSave();
            },
        });
    };
});
