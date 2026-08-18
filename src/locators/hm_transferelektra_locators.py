"""
Locators para el flujo: hm_transferelektra
Pantalla real de Transfers de Hermes2 — la reutilizan TODOS los pagadores del
catálogo (src/pagadores/<pais>/payers.json) vía src/pagadores/flujo_mt.py.
"""


class HmTransferelektraLocators:
    """Selectores del flujo hm_transferelektra."""

    # [transfers] transfer-customer-cellphone-0-cellphone-input
    TRANSFER_CUSTOMER_CELLPHONE_0_CELLPHONE_INPUT           = "transfer-customer-cellphone-0-cellphone-input"  # data-testid

    # [transfers] transfer-customer-name-0-input
    TRANSFER_CUSTOMER_NAME_0_INPUT                          = "transfer-customer-name-0-input"  # data-testid

    # [transfers] transfer-customer-first-lastName-0-input
    TRANSFER_CUSTOMER_FIRST_LASTNAME_0_INPUT                = "transfer-customer-first-lastName-0-input"  # data-testid

    # [transfers] transfer-customer-second-lastname-0-input
    TRANSFER_CUSTOMER_SECOND_LASTNAME_0_INPUT               = "transfer-customer-second-lastname-0-input"  # data-testid

    # [transfers] Close Table
    CLOSE_TABLE                                             = "Close Table"

    # [transfers] transfer-customer-address-0-input
    TRANSFER_CUSTOMER_ADDRESS_0_INPUT                       = "transfer-customer-address-0-input"  # data-testid

    # [transfers] transfer-customer-zip-code-0-input
    TRANSFER_CUSTOMER_ZIP_CODE_0_INPUT                      = "transfer-customer-zip-code-0-input"  # data-testid

    # [transfers] transfer-beneficiary-toggle-fields-button-0
    TRANSFER_BENEFICIARY_TOGGLE_FIELDS_BUTTON_0             = "transfer-beneficiary-toggle-fields-button-0"  # data-testid

    # [transfers] transfer-beneficiary-clear-0-icon-svg
    TRANSFER_BENEFICIARY_CLEAR_0_ICON_SVG                   = "transfer-beneficiary-clear-0-icon-svg"  # data-testid

    # [transfers] transfer-beneficiary-country-0-dropdown-input
    TRANSFER_BENEFICIARY_COUNTRY_0_DROPDOWN_INPUT           = "transfer-beneficiary-country-0-dropdown-input"  # data-testid

    # [transfers] Beneficiary
    TRANSFER_BENEFICIARY_SUBTITLE_0                         = "transfer-beneficiary-subtitle-0"  # data-testid

    # [transfers] transfer-beneficiary-name-0-dropdown-input
    TRANSFER_BENEFICIARY_NAME_0_DROPDOWN_INPUT              = "transfer-beneficiary-name-0-dropdown-input"  # data-testid

    # [transfers] transfer-beneficiary-first-lastname-0-input
    TRANSFER_BENEFICIARY_FIRST_LASTNAME_0_INPUT             = "transfer-beneficiary-first-lastname-0-input"  # data-testid

    # [transfers] transfer-beneficiary-second-lastname-0-input
    TRANSFER_BENEFICIARY_SECOND_LASTNAME_0_INPUT            = "transfer-beneficiary-second-lastname-0-input"  # data-testid

    # [transfers] transfer-beneficiary-cellphone-0-cellphone-input
    TRANSFER_BENEFICIARY_CELLPHONE_0_CELLPHONE_INPUT        = "transfer-beneficiary-cellphone-0-cellphone-input"  # data-testid

    # [transfers] transfer-beneficiary-address-0-input
    TRANSFER_BENEFICIARY_ADDRESS_0_INPUT                    = "transfer-beneficiary-address-0-input"  # data-testid

    # [transfers] transfer-beneficiary-zip-code-0-input
    TRANSFER_BENEFICIARY_ZIP_CODE_0_INPUT                   = "transfer-beneficiary-zip-code-0-input"  # data-testid

    # [transfers] transfer-beneficiary-city-0-input
    TRANSFER_BENEFICIARY_CITY_0_INPUT                       = "transfer-beneficiary-city-0-input"  # data-testid

    # [transfers] transfer-beneficiary-state-0-input
    TRANSFER_BENEFICIARY_STATE_0_INPUT                      = "transfer-beneficiary-state-0-input"  # data-testid

    # [transfers] transfer-beneficiary-date-of-birth-0-input
    TRANSFER_BENEFICIARY_DATE_OF_BIRTH_0_INPUT              = "transfer-beneficiary-date-of-birth-0-input"  # data-testid

    # [transfers] transfer-beneficiary-email-0-input
    TRANSFER_BENEFICIARY_EMAIL_0_INPUT                      = "transfer-beneficiary-email-0-input"  # data-testid

    # [transfers] transfer-payers-money-info-city-0-cash-dropdown-input
    TRANSFER_PAYERS_MONEY_INFO_CITY_0_CASH_DROPDOWN_INPUT   = "transfer-payers-money-info-city-0-cash-dropdown-input"  # data-testid

    # [transfers] p-element
    TRANSFER_PAYERS_MONEY_INFO_FEE_TYPE_0_CASH_DROPDOWN_INPUT = "transfer-payers-money-info-fee-type-0-cash-dropdown-input"  # data-testid

    # [transfers] MEXICO REGULAR
    TRANSFER_PAYERS_MONEY_INFO_FEE_TYPE_0_CASH_DROPDOWN_INPUT_click = "transfer-payers-money-info-fee-type-0-cash-dropdown-input"  # data-testid

    # [transfers] transfer-payers-money-info-amount-0-cash-amount-input
    TRANSFER_PAYERS_MONEY_INFO_AMOUNT_0_CASH_AMOUNT_INPUT   = "transfer-payers-money-info-amount-0-cash-amount-input"  # data-testid

    # [transfers] transfer-payers-money-info-payer-0-cash-input
    TRANSFER_PAYERS_MONEY_INFO_PAYER_0_CASH_INPUT           = "transfer-payers-money-info-payer-0-cash-input"  # data-testid

    # [transfers] transfers-money-info-modal-search-payer-0-input-search-input
    TRANSFERS_MONEY_INFO_MODAL_SEARCH_PAYER_0_INPUT_SEARCH_INPUT = "transfers-money-info-modal-search-payer-0-input-search-input"  # data-testid

    # [transfers] ELEKTRA DIRECTO
    ELEKTRA_DIRECTO                                         = "ELEKTRA DIRECTO"

    # [transfers] Branch
    BUTTON_ID_1                                             = "#button_id-1"

    # [transfers] DAZ JAL SAN JOAQUIN GUAD
    DAZ_JAL_SAN_JOAQUIN_GUAD                                = "DAZ JAL SAN JOAQUIN GUAD"

    # [transfers] Continue
    TRANSFER_CONTINUE_BUTTON_0_BUTTON                       = "transfer-continue-button-0-button"  # data-testid

    # [transfers] YES, Send
    TRANSFERS_CONTAINER_MODAL_SUMMARY_0_SEND_BUTTON         = "transfers-container-modal-summary-0-send-button"  # data-testid

    # [transfers] NO
    TRANSFERS_CONTAINER_MODAL_SUCCESS_TRANSFER_0_DECLINE_BUTTON = "transfers-container-modal-success-transfer-0-decline-button"  # data-testid

    # [transfers] Reports
    REPORTS_NAVBAR_ITEM                                     = "reports-navbar-item"  # data-testid

    # [transfers] Transactions
    REPORTS_2_NAVBAR_DROPDOWN_ITEM                          = "reports-2-navbar-dropdown-item"  # data-testid

    # [transfers] YES, Leave
    MODAL_CONFIRMATION_DENY_BUTTON                          = "modal-confirmation-deny-button"  # data-testid

    # [reports_transaction] Search
    TEST_ID_BUTTON                                          = "test-id-button"  # data-testid

    # [reports_transaction] Cancel
    REPORTS_TRANSACTION_MENU__CANCEL_ICON_SVG               = "reports-transaction-menu--cancel-icon-svg"  # data-testid

    # [reports_transaction] p-element
    SELECT_FIELD_DROPDOWN_INPUT                             = "select-field-dropdown-input"  # data-testid

    # [reports_transaction] Client request (No reason)
    SELECT_FIELD_DROPDOWN_INPUT_click                       = "select-field-dropdown-input"  # data-testid

    # [reports_transaction] modal-cancel-transaction-notes-input
    MODAL_CANCEL_TRANSACTION_NOTES_INPUT                    = "modal-cancel-transaction-notes-input"  # data-testid

    # [reports_transaction] Transfers
    DROPDOWN                                                = "[aria-label=\"dropdown\"]"
