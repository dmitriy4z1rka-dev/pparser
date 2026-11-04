define('custom:controllers/local-home', ['controllers/base'], function (Controller) {
    return class extends Controller {
        actionIndex() {
            this.getRouter().navigate('Lead', {trigger: true});
        }
    };
});
