define('custom:views/user-detail', ['views/user/record/detail'], function (UserDetailRecordView) {
    return class extends UserDetailRecordView {
        addButton(button) {
            if (['access', 'viewSecurity'].includes(button.name)) return;
            return super.addButton(button);
        }

        addDropdownItem(item) {
            if (['changePassword', 'sendPasswordChangeLink', 'generateNewPassword', 'login', 'generateNewApiKey'].includes(item.name)) return;
            return super.addDropdownItem(item);
        }
    };
});
