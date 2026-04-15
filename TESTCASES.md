# Test Case Documentation

---

## TC-001: Producer Account Registration
**Priority:** `CRITICAL`  
**Stakeholder:** Producer  
**User Story:** As a producer, I want to create an account so that I can list my products on the marketplace.

### Description
Validates that producers can successfully register for the marketplace platform with required business information and receive appropriate authentication credentials.

### Preconditions
* The system is accessible and running.
* No existing account with the test email address.

### Test Steps
1. Navigate to the producer registration page.
2. Enter business name: **Bristol Valley Farm**.
3. Enter contact name: **Jane Smith**.
4. Enter email: **jane.smith@bristolvalleyfarm.com**.
5. Enter phone: **01179 123456**.
6. Enter business address and postcode: **BS1 4DJ**.
7. Enter password meeting security requirements.
8. Confirm password.
9. Submit registration form.

### Expected Results
* Registration form accepts all valid inputs without error.
* Account is created successfully with producer role.
* Producer receives confirmation message.
* Producer can log in with registered credentials.
* Producer profile is accessible with entered business information.

### Acceptance Criteria
* Producer account is created in the system.
* Password is securely stored (hashed).
* Business information is correctly saved.
* Producer can authenticate using email and password.
* Appropriate producer permissions are assigned to the account.

---

## TC-002: Customer Account Registration
**Priority:** `CRITICAL`  
**Stakeholder:** Customer (Young Professional/Family)  
**User Story:** As a customer, I want to register for an account so that I can browse and purchase local products.

### Description
Validates that customers can successfully create accounts with personal information and delivery address details for purchasing purposes.

### Preconditions
* The system is accessible and running.
* No existing account with the test email address.

### Test Steps
1. Navigate to the customer registration page.
2. Enter full name: **Robert Johnson**.
3. Enter email: **robert.johnson@email.com**.
4. Enter phone: **07700 900123**.
5. Enter delivery address: **45 Park Street, Bristol**.
6. Enter postcode: **BS1 5JG**.
7. Enter password meeting security requirements.
8. Confirm password.
9. Accept terms and conditions.
10. Submit registration form.

### Expected Results
* Registration form accepts all valid inputs.
* Customer account is created successfully.
* Customer receives confirmation message.
* Customer can log in with registered credentials.
* Delivery address is stored for future orders.

### Acceptance Criteria
* Customer account is created with appropriate role.
* Personal information is securely stored.
* Delivery address is saved and linked to customer profile.
* Customer can authenticate successfully.
* Customer has browsing and purchasing permissions.

---

## TC-003: Producer Product Listing
**Priority:** `CRITICAL`  
**Stakeholder:** Producer  
**User Story:** As a producer, I want to list a new product so that customers can find and purchase it.

### Description
Validates that authenticated producers can successfully create product listings with all required information including seasonal availability.

### Preconditions
* Producer is logged in to the system.
* Producer has a verified account.

### Test Steps
1. Navigate to the product management section.
2. Click **'Add New Product'**.
3. Enter product name: **Organic Free Range Eggs**.
4. Select category: **Dairy & Eggs**.
5. Enter detailed description: **Fresh organic eggs from free-range hens, collected daily**.
6. Enter price: **£3.50 per dozen**.
7. Enter unit: **Dozen**.
8. Set availability: **In Season (Available)**.
9. Enter stock quantity: **50**.
10. Add allergen information: **Contains eggs**.
11. Set harvest date: **Current date**.
12. Upload product image (optional).
13. Submit product listing.

### Expected Results
* Product form accepts all valid inputs.
* Product is created and saved to the database.
* Product appears in producer's product management dashboard.
* Product becomes visible to customers in the marketplace.
* All product details are correctly displayed.

### Acceptance Criteria
* Product is linked to the authenticated producer.
* All required fields are validated and stored.
* Product appears in search and category browsing.
* Seasonal availability status is correctly displayed.
* Stock quantity is tracked for inventory management.

---

## TC-004: Browse Products by Category
**Priority:** `CRITICAL`  
**Stakeholder:** Customer (All types)  
**User Story:** As a customer, I want to browse products by category so that I can find specific items I need.

### Description
Validates that customers can effectively browse products organised by categories such as vegetables, dairy, bakery, preserves, and seasonal specialties.

### Preconditions
* Multiple products exist in different categories.
* At least 5 products in the **Vegetables** category.
* At least 3 products in the **Dairy** category.

### Test Steps
1. Navigate to the marketplace homepage.
2. View the category navigation menu.
3. Click on **'Vegetables'** category.
4. Observe displayed products.
5. Return to main categories.
6. Click on **'Dairy Products'** category.
7. Observe displayed products.
8. Verify each product shows key information: name, price, farm origin, availability.

### Expected Results
* Category navigation is clearly visible.
* Clicking 'Vegetables' displays only vegetable products.
* Clicking 'Dairy Products' displays only dairy products.
* Each category shows appropriate products with correct categorization.
* Products display name, price, producer name, and availability status.
* Category pages load without errors.

### Acceptance Criteria
* Products are correctly categorised.
* Category filtering works accurately.
* Only products marked as 'Available' or 'In Season' are displayed.
* Product information is complete and readable.
* Navigation between categories is intuitive.

---

## TC-005: Product Search Functionality
**Priority:** `HIGH`  
**Stakeholder:** Customer (All types)  
**User Story:** As a customer, I want to search for specific products so that I can quickly find what I need.

### Description
Validates that the search functionality enables customers to locate products efficiently using product names, descriptions, or producer names.

### Preconditions
* Multiple products exist in the database.
* Products have descriptive names and detailed descriptions.
* Search functionality is enabled.

### Test Steps
1. Navigate to the marketplace homepage.
2. Locate the search bar.
3. Enter search term: **tomatoes**.
4. Submit search and observe results.
5. Clear search.
6. Enter search term: **organic**.
7. Submit search and observe results (including products from different categories).
8. **Edge Case:** Enter a non-existent product name and observe empty results handling.

### Expected Results
* Search bar is visible and accessible.
* Searching for 'tomatoes' returns all tomato products.
* Searching for 'organic' returns all products with 'organic' in the name or description.
* Search results display product name, price, producer, and category.
* Search for non-existent items shows an appropriate 'no results found' message.
* Search is case-insensitive.

### Acceptance Criteria
* Search queries return relevant results based on product name and description.
* Search functionality handles partial matches appropriately.
* Empty search results are handled gracefully.
* Search performance is acceptable.

---

## TC-006: Shopping Cart Management
**Priority:** `CRITICAL`  
**Stakeholder:** Customer (All types)  
**User Story:** As a customer, I want to add products to my shopping cart so that I can purchase multiple items together.

### Description
Validates that customers can add products to a shopping cart, modify quantities, and view cart contents before proceeding to checkout.

### Preconditions
* Customer is logged in.
* Multiple products are available for purchase.
* Shopping cart functionality is enabled.

### Test Steps
1. Browse or search for: **Organic Carrots**.
2. View product details.
3. Select quantity: **2 kg** and click **'Add to Cart'**.
4. Observe confirmation message.
5. Navigate to another product: **Fresh Milk**.
6. Select quantity: **3 litres** and click **'Add to Cart'**.
7. Click on the cart icon to view contents.
8. Verify both products appear with correct quantities and prices.
9. Modify quantity of Organic Carrots to **3 kg**.
10. Observe updated total price.

### Expected Results
* Products can be added to cart successfully.
* Cart icon displays correct item count.
* Cart page shows all added products with correct details.
* Individual item prices and total cart price are calculated correctly.
* Quantity modifications update prices in real-time.
* Cart persists during the browsing session.

### Acceptance Criteria
* Cart maintains state for logged-in customers.
* Item quantities can be modified or removed.
* Price calculations are accurate.
* Cart displays producer information for multi-vendor awareness.

---

## TC-007: Single Producer Checkout Process
**Priority:** `CRITICAL`  
**Stakeholder:** Customer (All types)  
**User Story:** As a customer, I want to place an order from a single producer so that I can purchase their products.

### Description
Validates the complete checkout process for orders containing products from a single producer, including payment processing and order confirmation.

### Preconditions
* Customer is logged in with a saved delivery address.
* Cart contains products from **only one** producer.
* Payment system is configured (test mode).
* Producer has a minimum 48-hour lead time setting.

### Test Steps
1. Add products from **'Bristol Valley Farm'** to cart.
2. Navigate to the cart page and confirm items are from a single producer.
3. Click **'Proceed to Checkout'**.
4. Verify delivery address is pre-filled.
5. Select a delivery date (must be at least 48 hours from current date).
6. Review order summary (check producer details).
7. Choose payment method and enter test credentials.
8. Confirm order.

### Expected Results
* Checkout page loads with correct cart contents.
* Delivery address is displayed and editable.
* Delivery date selector enforces the 48-hour lead time.
* Order summary shows itemised products, subtotal, and **5% commission**.
* Payment is processed successfully (test mode).
* Order confirmation page displays an order number.
* Both customer and producer receive notifications/confirmation.

### Acceptance Criteria
* Order is created in the database with **'Pending'** status.
* Payment transaction is recorded.
* 5% network commission is calculated and recorded.
* Producer payment (95% of order value) is calculated.
* Order details include delivery date and customer information.

---

## TC-008: Multi-Vendor Checkout Process
**Priority:** `CRITICAL`  
**Stakeholder:** Customer (All types)  
**User Story:** As a customer, I want to place an order from multiple producers so that I can purchase various products in one transaction.

### Description
Validates the multi-vendor checkout process including clear separation of producer responsibilities, individual delivery arrangements, and payment distribution.

### Preconditions
* Customer is logged in.
* Cart contains products from at least 2 different producers.
* Payment system is configured (test mode).

### Test Steps
1. Add 2 products from **'Bristol Valley Farm'** to cart.
2. Add 2 products from **'Hillside Dairy'** to cart.
3. Navigate to cart and verify products are grouped by producer.
4. Click **'Proceed to Checkout'**.
5. Review order summary showing separate sections for each producer.
6. Note individual producer delivery information and select delivery dates for each (based on their lead times).
7. Review total cost breakdown showing per-producer subtotals.
8. Enter payment details and confirm the multi-vendor order.

### Expected Results
* Cart clearly groups products by producer.
* Checkout displays separate sections for each producer with their specific delivery requirements.
* Order supports different delivery dates per producer.
* Payment is split: 5% commission on total; each producer receives 95% of their item values.
* Order confirmation and notifications are correctly partitioned by producer.

### Acceptance Criteria
* Multi-vendor order is recorded as a single customer order with linked sub-orders.
* Payment distribution and 5% network commission are calculated correctly.
* Producers only see their relevant items; customers see the unified order view.

---

## TC-009: Producer Order Management Dashboard
**Priority:** `CRITICAL`  
**Stakeholder:** Producer  
**User Story:** As a producer, I want to view incoming orders so that I can prepare products for delivery.

### Description
Validates that producers can access a dashboard showing all incoming orders with adequate lead time and complete customer details for preparation and delivery.

### Preconditions
* Producer is logged in.
* At least 3 orders exist for this producer with different delivery dates.

### Test Steps
1. Log in as producer and navigate to **'Order Management'**.
2. View list of incoming orders (verify: order #, customer name, delivery date, items, total value).
3. Click a specific order to view full details (address, contact info, itemised list, special instructions).
4. Verify orders are sorted by delivery date.
5. Confirm all orders respect the minimum 48-hour lead time.

### Expected Results
* Producer can access the dashboard and view only their specific items.
* All essential preparation and delivery information is visible.
* Statuses (Pending, Confirmed, Ready, Delivered) are clearly indicated.
* Delivery dates accurately reflect the 48-hour lead time requirement.

### Acceptance Criteria
* Multi-vendor orders show only this producer's items.
* Producer cannot access other producers' orders.
* Customer contact information is accessible for coordination.

---

## TC-010: Order Status Lifecycle Updates
**Priority:** `HIGH`  
**Stakeholder:** Producer  
**User Story:** As a producer, I want to update the status of orders so that customers know when their products are ready.

### Description
Validates that producers can update order statuses through the order lifecycle and customers receive appropriate notifications.

### Preconditions
* Producer is logged in.
* At least one order exists with **'Pending'** status.

### Test Steps
1. Navigate to order management dashboard.
2. Select a **'Pending'** order and click **'Update Status'**.
3. Change status to **'Confirmed'** and add an optional note.
4. Save update and verify status change.
5. Later, update the status to **'Ready for Collection/Delivery'**.
6. Verify the customer receives a notification in their account.

### Expected Results
* Status updates are saved and reflected immediately.
* Order history shows a timestamped status change timeline.
* Optional notes are included in the update.
* Customer view and notifications are triggered correctly.

### Acceptance Criteria
* Status follows logical progression: **Pending → Confirmed → Ready → Delivered**.
* Only the relevant producer can update their portion of an order.
* Audit trail maintains all changes.

---

## TC-011: Inventory and Availability Management
**Priority:** `HIGH`  
**Stakeholder:** Producer  
**User Story:** As a producer, I want to update my product inventory so that customers only see available products I have.

### Description
Validates that producers can modify product availability and stock quantities without requiring technical expertise.

### Preconditions
* Producer is logged in.
* Producer has at least 3 listed products with various stock levels.

### Test Steps
1. Navigate to the product management dashboard.
2. Select **'Organic Tomatoes'** (or similar) and click **'Edit'**.
3. Change stock quantity (e.g., to 35 kg) and set status to **'In Season'**.
4. Save changes.
5. Select an out-of-stock product and set status to **'Unavailable'**.
6. Save and verify changes in the customer marketplace view.

### Expected Results
* Stock and availability updates save successfully.
* Products marked 'Unavailable' are hidden from customer browsing.
* Changes take effect immediately in search results and product pages.

### Acceptance Criteria
* Producers can only edit their own products.
* Stock updates are validated (non-negative numbers).
* Product update history is maintained.

---

## TC-012: Weekly Payment Settlements
**Priority:** `CRITICAL`  
**Stakeholder:** Producer  
**User Story:** As a producer, I want to receive weekly payment settlements so that I can manage my business finances.

### Description
Validates the payment settlement system that distributes 95% of order value to producers weekly with transparent audit trails.

### Preconditions
* Producer has completed orders from the previous week.
* Payment week has ended (Sunday midnight).
* Orders have been delivered/completed.
* Payment system is configured.

### Test Steps
1. Log in as producer on Monday after the settlement week.
2. Navigate to **'Payments'** or **'Financial Reports'**.
3. View the weekly payment summary for the completed week.
4. Verify details: total order value, 5% commission deduction, 95% producer payment, and individual order breakdown.
5. Download the payment report (PDF or CSV) for tax records.
6. Verify report contains: order numbers, anonymised customer names, items sold, dates, and commission breakdown.
7. Check payment status (e.g., 'Processed' or 'Pending Bank Transfer').
8. Verify the running total for the tax year is displayed.

### Expected Results
* Weekly summary is accessible and accurate.
* All completed/delivered orders from the week are included.
* Calculations for commission (5%) and producer payout (95%) are correct.
* Reports are downloadable and include necessary details for accounting/tax.
* Historical records and transaction IDs are provided.

### Acceptance Criteria
* Calculations are accurate to 2 decimal places.
* Only completed orders are included in settlements.
* Settlement timeline adheres to the weekly schedule.
* Audit trail links payments directly to specific orders.

---

## TC-013: Food Miles Calculation
**Priority:** `MEDIUM`  
**Stakeholder:** Customer (All types)  
**User Story:** As a customer, I want to view food miles for products so that I can make environmentally conscious purchases.

### Description
Validates the environmental reporting feature that calculates and displays food miles based on customer postcode and producer farm location.

### Preconditions
* Customer is logged in with postcode (e.g., **BS1 5JG**).
* Producer farm locations are recorded.
* Products are correctly associated with producer locations.

### Test Steps
1. Browse products and select one from **'Bristol Valley Farm'** (located at **BS1 4DJ**).
2. Observe the food miles display on the product details page.
3. Compare the distance with a producer located further away (e.g., 15 miles).
4. Add both products to the cart.
5. View the cart page and observe the total food miles calculation.
6. Verify the total is the sum of the individual product distances.

### Expected Results
* Food miles are displayed prominently via a badge or icon.
* Distance calculation is accurate between customer and producer postcodes.
* Cart view correctly displays cumulative food miles.
* Closer producers show lower food mile counts.

### Acceptance Criteria
* Calculations update automatically if the customer changes their delivery address.
* Visual representation is clear and easy to understand.
* Calculation supports the network's **20-mile radius** commitment.

---

## TC-014: Organic Certification Filtering
**Priority:** `MEDIUM`  
**Stakeholder:** Customer (Young Professional/Family)  
**User Story:** As a customer, I want to filter products by organic certification so that I can find certified organic items.

### Description
Validates quality assurance features allowing customers to filter and identify products with organic certification status.

### Preconditions
* Products exist with varying certification statuses (at least 5 'Certified Organic' and 5 'Not Certified').

### Test Steps
1. Navigate to the product browsing page.
2. Locate and select the **'Organic Certification'** filter.
3. Enable the filter for **'Certified Organic'** only.
4. Observe the results and verify all displayed products show a certification badge.
5. Click a product to verify certification details on the product page.
6. Clear the filter and verify all products return.
7. **Edge Case:** Apply the filter in a category with no organic products and observe the empty results message.

### Expected Results
* Filter excludes non-certified products accurately.
* Organic certification indicator is clearly visible on filtered results.
* Filter can be easily applied and removed.
* Appropriate "no results" message is shown for empty filter hits.

### Acceptance Criteria
* Certification status is accurately maintained for each product.
* Filter works consistently across all categories.
* Visual indicators clearly distinguish certified vs. non-certified items.
* Filter combines logically with other parameters (price, category, etc.).

---

## TC-012: Weekly Payment Settlements
**Priority:** `CRITICAL`  
**Stakeholder:** Producer  
**User Story:** As a producer, I want to receive weekly payment settlements so that I can manage my business finances.

### Description
Validates the payment settlement system that distributes 95% of order value to producers weekly with transparent audit trails.

### Preconditions
* Producer has completed orders from the previous week.
* Payment week has ended (Sunday midnight).
* Orders have been delivered/completed.
* Payment system is configured.

### Test Steps
1. Log in as producer on Monday after the settlement week.
2. Navigate to **'Payments'** or **'Financial Reports'**.
3. View the weekly payment summary for the completed week.
4. Verify details: total order value, 5% commission deduction, 95% producer payment, and individual order breakdown.
5. Download the payment report (PDF or CSV) for tax records.
6. Verify report contains: order numbers, anonymised customer names, items sold, dates, and commission breakdown.
7. Check payment status (e.g., 'Processed' or 'Pending Bank Transfer').
8. Verify the running total for the tax year is displayed.

### Expected Results
* Weekly summary is accessible and accurate.
* All completed/delivered orders from the week are included.
* Calculations for commission (5%) and producer payout (95%) are correct.
* Reports are downloadable and include necessary details for accounting/tax.
* Historical records and transaction IDs are provided.

### Acceptance Criteria
* Calculations are accurate to 2 decimal places.
* Only completed orders are included in settlements.
* Settlement timeline adheres to the weekly schedule.
* Audit trail links payments directly to specific orders.

---

## TC-013: Food Miles Calculation
**Priority:** `MEDIUM`  
**Stakeholder:** Customer (All types)  
**User Story:** As a customer, I want to view food miles for products so that I can make environmentally conscious purchases.

### Description
Validates the environmental reporting feature that calculates and displays food miles based on customer postcode and producer farm location.

### Preconditions
* Customer is logged in with postcode (e.g., **BS1 5JG**).
* Producer farm locations are recorded.
* Products are correctly associated with producer locations.

### Test Steps
1. Browse products and select one from **'Bristol Valley Farm'** (located at **BS1 4DJ**).
2. Observe the food miles display on the product details page.
3. Compare the distance with a producer located further away (e.g., 15 miles).
4. Add both products to the cart.
5. View the cart page and observe the total food miles calculation.
6. Verify the total is the sum of the individual product distances.

### Expected Results
* Food miles are displayed prominently via a badge or icon.
* Distance calculation is accurate between customer and producer postcodes.
* Cart view correctly displays cumulative food miles.
* Closer producers show lower food mile counts.

### Acceptance Criteria
* Calculations update automatically if the customer changes their delivery address.
* Visual representation is clear and easy to understand.
* Calculation supports the network's **20-mile radius** commitment.

---

## TC-014: Organic Certification Filtering
**Priority:** `MEDIUM`  
**Stakeholder:** Customer (Young Professional/Family)  
**User Story:** As a customer, I want to filter products by organic certification so that I can find certified organic items.

### Description
Validates quality assurance features allowing customers to filter and identify products with organic certification status.

### Preconditions
* Products exist with varying certification statuses (at least 5 'Certified Organic' and 5 'Not Certified').

### Test Steps
1. Navigate to the product browsing page.
2. Locate and select the **'Organic Certification'** filter.
3. Enable the filter for **'Certified Organic'** only.
4. Observe the results and verify all displayed products show a certification badge.
5. Click a product to verify certification details on the product page.
6. Clear the filter and verify all products return.
7. **Edge Case:** Apply the filter in a category with no organic products and observe the empty results message.

### Expected Results
* Filter excludes non-certified products accurately.
* Organic certification indicator is clearly visible on filtered results.
* Filter can be easily applied and removed.
* Appropriate "no results" message is shown for empty filter hits.

### Acceptance Criteria
* Certification status is accurately maintained for each product.
* Filter works consistently across all categories.
* Visual indicators clearly distinguish certified vs. non-certified items.
* Filter combines logically with other parameters (price, category, etc.).

---

## TC-015: Allergen Warning Display
**Priority:** `CRITICAL`  
**Stakeholder:** Customer (All types)  
**User Story:** As a customer, I want to see allergen warnings clearly displayed so that I can avoid products that may harm me or my family.

### Description
Validates that allergen information is prominently displayed for food safety and customer protection, supporting compliance with food safety regulations (e.g., UK 14 major allergens).

### Preconditions
* Products have allergen information recorded.
* At least 3 products contain common allergens (dairy, eggs, nuts, gluten).
* Some products are marked with no allergens.

### Test Steps
1. Browse to a product containing dairy (e.g., **Cheddar Cheese**).
2. View product details and locate the allergen section.
3. Verify **'Contains: Milk'** is clearly displayed.
4. Browse to a product with multiple allergens (e.g., **Walnut Bread**).
5. Verify multiple allergens are listed individually: **'Contains: Wheat (Gluten), Nuts (Walnuts)'**.
6. Browse to a product with no allergens (e.g., **Fresh Apples**) and verify it states **'No common allergens'**.
7. Search for 'nuts' and verify results allow allergen-based identification.

### Expected Results
* Allergen warnings use clear, standard language and stand out visually (icons/colors).
* Multiple allergens are listed individually.
* Information is visible *before* adding the item to the cart.
* Products without allergens explicitly state their status.

### Acceptance Criteria
* Producers cannot omit allergen information for food products.
* Display meets food safety labelling requirements.
* Customers can filter products by allergen presence/absence.

---

## TC-016: Seasonal Availability Management
**Priority:** `HIGH`  
**Stakeholder:** Producer  
**User Story:** As a producer, I want to set seasonal availability for my products so that customers know when items are in season.

### Description
Validates that producers can manage seasonal availability without technical expertise and that customers see accurate seasonal indicators and date ranges.

### Preconditions
* Producer is logged in.
* Producer has products with varying seasonal patterns.

### Test Steps
1. Navigate to product management and select **'Strawberries'**.
2. Set availability to **'In Season'** and define dates: **June - August**.
3. Save changes.
4. Select **'Stored Potatoes'** and set availability to **'Available Year-Round'**.
5. Log in as a customer and browse the marketplace.
6. Verify Strawberries show an **'In Season'** badge and the specific date range.
7. Verify year-round products show no seasonal restrictions.

### Expected Results
* Producers can easily specify date ranges for seasonal items.
* Out-of-season products are hidden or marked as unavailable.
* System can automatically update availability based on the current date.

### Acceptance Criteria
* Seasonal settings are intuitive for non-technical users.
* Customers cannot order products that are currently out of season.
* Producers receive reminders when seasonal products are about to become available.

---

## TC-017: Community Group Bulk Ordering
**Priority:** `MEDIUM`  
**Stakeholder:** Customer (Community Group)  
**User Story:** As a community group representative, I want to place bulk orders from multiple producers for catering needs.

### Description
Validates that community groups (schools, charities, etc.) can create specialized accounts and place large-scale orders with multiple suppliers for institutional catering.

### Preconditions
* Community group account type is enabled in the system.
* Bulk ordering functionality is active.

### Test Steps
1. Register as a community group (e.g., **'St. Mary's School'**) using an institutional email.
2. Provide organization details and charity/education status.
3. Log in and add large quantities to the cart (e.g., **50 kg potatoes, 30L milk**) from at least 3 different producers.
4. Proceed to checkout and enter the school delivery address.
5. Add special instructions (e.g., **"Delivery to kitchen entrance"**).
6. Review the multi-vendor order summary and complete payment.

### Expected Results
* System accepts and validates larger quantities.
* Checkout handles multi-vendor bulk logic seamlessly.
* Special delivery instructions are captured and sent to all relevant producers.
* Confirmation includes specific contact details for all suppliers involved.

### Acceptance Criteria
* Community group accounts are distinguished from individual retail customers.
* Bulk quantities are validated against known producer capacities.
* Payment terms (such as invoicing) may differ for institutional buyers.

---

## TC-018: Recurring Orders for Restaurants
**Priority:** `MEDIUM`  
**Stakeholder:** Customer (Independent Restaurant)  
**User Story:** As a restaurant owner, I want to establish regular weekly orders so that I can simplify sourcing local ingredients.

### Description
Validates that business customers can set up recurring orders to reduce administrative overhead of managing multiple small supplier relationships.

### Preconditions
* Restaurant business account is created and verified.
* Multiple products from various producers are available.
* Recurring order functionality exists.

### Test Steps
1. Log in as restaurant account: **The Clifton Kitchen**.
2. Create an initial order with required weekly ingredients (vegetables, dairy, bakery).
3. Set specific quantities for each item.
4. Before checkout, select **'Make this a recurring order'**.
5. Set recurrence to **Every Monday** and delivery to **Every Wednesday**.
6. Review and confirm the recurring order setup.
7. Navigate to the **'Recurring Orders'** management page.
8. Modify next week's order (e.g., increase quantity of one item).
9. Verify modification applies only to the next order instance, not the template.

### Expected Results
* Restaurant can create templates with specific recurrence (weekly, fortnightly).
* New orders are automatically generated based on the schedule.
* Each scheduled instance can be edited individually before confirmation.
* Producers receive advance notice; restaurants can pause or cancel at any time.
* System handles producer availability changes gracefully.

### Acceptance Criteria
* Template maintains product selections and quantities correctly.
* Order generation respects producer lead time requirements.
* Notifications are sent to the restaurant before each order processes.
* Unavailable products in a recurring cycle trigger immediate alerts.

---

## TC-019: Surplus Produce and Discounts
**Priority:** `MEDIUM`  
**Stakeholder:** Producer  
**User Story:** As a producer, I want to communicate surplus produce with discounts so that I can reduce food waste.

### Description
Validates the surplus produce feature allowing producers to offer last-minute discounts on excess inventory to prevent food waste.

### Preconditions
* Producer is logged in with stock that needs to be sold quickly.
* Surplus produce feature is enabled.

### Test Steps
1. Navigate to product management and select **Lettuce** (e.g., 50 heads, best before 3 days).
2. Click **'Mark as Surplus'** or **'Last Minute Deal'**.
3. Set a **30% discount** and an expiry date of **48 hours**.
4. Add a note: *"Perfect condition, must sell quickly to avoid waste"*.
5. Save the listing and verify it appears in the customer **'Surplus Deals'** section.
6. Log in as a customer, navigate to deals, and verify the original vs. discounted price.
7. Add to cart and complete the purchase at the reduced price.

### Expected Results
* Discount and urgency (time remaining) are prominently displayed.
* Discounted price is correctly calculated and applied at checkout.
* Deals expire automatically after the specified timeframe.
* Feature supports community food waste reduction goals.

### Acceptance Criteria
* Discount percentages are validated (e.g., within a 10-50% range).
* Surplus items maintain all quality and allergen information.
* Producers can manually remove surplus status if stock sells out early.
* Analytics track the impact of food waste reduction.

---

## TC-020: Recipes and Farm Stories
**Priority:** `LOW`  
**Stakeholder:** Producer  
**User Story:** As a producer, I want to share recipes and farm stories so that I can engage with the community and educate customers.

### Description
Validates educational features allowing producers to share seasonal recipes, storage guidance, and farm stories to strengthen community connections.

### Preconditions
* Producer is logged in.
* Content management feature is available.

### Test Steps
1. Navigate to **'Content'** or **'Farm Stories'**.
2. Click **'Add New Recipe'** (e.g., "Roasted Root Vegetable Medley").
3. Add description, ingredients, and link to products: **Carrots, Parsnips, Potatoes**.
4. Upload an image, add instructions, and apply the **Autumn/Winter** tag.
5. Create a **Farm Story** post with harvest photos and publish.
6. Log in as a customer and view the **Carrots** product page.
7. Verify the **'Recipe Suggestions'** section displays the linked recipe.
8. Navigate to the producer profile to view stories and educational content.

### Expected Results
* Producers can create formatted recipes and stories with images.
* Recipes correctly link to specific inventory items for easy purchase.
* Content is easily accessible to customers via product pages or profiles.
* Seasonal tags help organize and filter content.

### Acceptance Criteria
* Recipe format is user-friendly and readable.
* Product links are clickable and lead directly to purchase options.
* Storage guidance helps customers maximize product freshness.
* Content supports local food education objectives.

---

## TC-021: Order History and Reordering
**Priority:** `HIGH`  
**Stakeholder:** Customer (All types)  
**User Story:** As a customer, I want to view my order history so that I can reorder favorite products and track past purchases.

### Description
Validates that customers can access complete order history with details and have the ability to quickly reorder previous purchases.

### Preconditions
* Customer is logged in.
* Customer has completed at least 3 orders in the past.
* Orders include various products and producers.

### Test Steps
1. Navigate to **'My Account'** or **'Order History'**.
2. View list of past orders sorted by date (most recent first).
3. Observe each order displays: order number, order date, delivery date, producer names, total amount, and order status.
4. Click on a completed order to view full details.
5. View itemised list of products with quantities and prices.
6. View delivery address and payment information (partially masked).
7. Click **'Reorder'** button on a previous order.
8. Observe items are added to current cart.
9. Verify product availability is checked.
10. Adjust quantities if needed and proceed to checkout.

### Expected Results
* Order history is accessible, complete, and sorted chronologically.
* Full order details are retrievable.
* Reorder function simplifies repeat purchases; unavailable products are flagged.
* Customer can filter orders by date range or producer.
* Multi-vendor orders show a clear producer breakdown.

### Acceptance Criteria
* All historical orders are permanently accessible.
* Reorder function handles product availability changes gracefully.
* Payment information is secure and appropriately masked.
* Order receipts can be downloaded for past purchases.

---

## TC-022: Secure Authentication and RBAC
**Priority:** `CRITICAL`  
**Stakeholder:** System (Security Requirement)  
**User Story:** As a system administrator, I want to ensure secure authentication so that user accounts and data are protected.

### Description
Validates authentication and authorisation mechanisms ensuring secure access control for all user types with appropriate permissions.

### Preconditions
* System is configured with an authentication system.
* User roles exist: Customer, Producer, Community Group, Restaurant, Admin.
* Test accounts exist for each role.

### Test Steps
1. **Password Security:** Attempt to register with a weak password ('123') and verify rejection. Register with a strong password and verify it is hashed in the database.
2. **Login Security:** Attempt login with an incorrect password; verify appropriate error message. Login with correct credentials and verify session creation.
3. **Authorisation:** Log in as a Customer and attempt to access producer-only features (add/edit products); verify access is denied. 
4. Log in as a Producer and attempt to view another producer's order details; verify access is denied.
5. **Session Management:** Log in, close browser, and reopen; verify session persists if 'remember me' was selected. Log out explicitly and verify session termination.

### Expected Results
* Password policy is enforced (length/complexity).
* Passwords are securely hashed using industry-standard algorithms.
* Authorisation checks prevent unauthorised feature access.
* Sessions are managed securely with appropriate timeouts.

### Acceptance Criteria
* Role-based access control (RBAC) is appropriately implemented.
* SQL injection and Cross-site scripting (XSS) are mitigated.
* Session tokens are secure and unguessable.
* Security logging captures all authentication events.

---

## TC-023: Low Stock Inventory Notifications
**Priority:** `MEDIUM`  
**Stakeholder:** Producer  
**User Story:** As a producer, I want to receive a notification when stock for a product runs low so that I can restock before orders fail.

### Description
Validates inventory management alerts that notify producers when product stock levels reach defined thresholds.

### Preconditions
* Producer is logged in.
* Products have stock quantities tracked.
* Low stock threshold feature is enabled and notification system is configured.

### Test Steps
1. Navigate to product management and edit product: **Fresh Eggs**.
2. Set current stock: **50 dozen**; set low stock threshold: **10 dozen**.
3. Simulate orders that reduce stock to 12 dozen (Verify no alert).
4. Simulate orders reducing stock to 9 dozen (Verify alert generation).
5. Check notification centre/dashboard for alert: *'Low Stock Alert: Fresh Eggs - Only 9 dozen remaining'*.
6. Update stock to 40 dozen and verify alert is cleared.

### Expected Results
* System monitors stock levels automatically and generates notifications below threshold.
* Alerts are displayed in the producer dashboard (and via email if configured).
* Alerts include product name and current stock level.
* Prevents accepting orders for out-of-stock items.

### Acceptance Criteria
* Stock tracking is accurate and real-time.
* Threshold settings are flexible per product.
* System can temporarily hide products from customer view when out of stock.
* Stock levels are automatically decremented when orders are placed.

---

## TC-024: Product Rating and Review System
**Priority:** `MEDIUM`  
**Stakeholder:** Customer (All types)  
**User Story:** As a customer, I want to rate and review products so that I can share my experience and help other customers make informed decisions.

### Description
Validates the review and rating system allowing customers to provide feedback on purchased products, supporting community trust.

### Preconditions
* Customer is logged in and has a delivered order containing product: **Organic Tomatoes**.
* Review system is enabled.

### Test Steps
1. Navigate to order history and open a **completed/delivered** order.
2. Locate 'Organic Tomatoes' and click **'Write Review'**.
3. Enter 5 stars, title: *'Excellent quality and flavour'*, and descriptive text.
4. Submit review and navigate to the product page.
5. Verify review appears with name, date, and **'Verified Purchase'** badge.
6. Observe average rating is updated.
7. **Edge Case:** Attempt to review a product from an order not yet delivered; verify system prevention.
8. **Edge Case:** Attempt to review the same product twice.

### Expected Results
* Reviews are linked to delivered orders (verified purchase).
* Average rating is calculated and displayed.
* System prevents duplicate reviews and reviews for undelivered items.
* Customer name is displayed (or anonymous option is honoured).

### Acceptance Criteria
* Rating scale is clear (1-5 stars).
* Producers can respond to reviews.
* Reviews are moderated for inappropriate content if needed.
* Aggregate ratings help customers make informed choices.

---

## TC-025: Financial Commission Monitoring
**Priority:** `HIGH`  
**Stakeholder:** System Administrator (Network Management)  
**User Story:** As a system administrator, I want to monitor the network commission calculations so that I can ensure financial accuracy and generate reports.

### Description
Validates that the 5% network commission is accurately calculated, recorded, and reportable across all transactions.

### Preconditions
* Admin user is logged in with appropriate permissions.
* Multiple orders exist (single and multi-vendor) from at least the previous 2 weeks.

### Test Steps
1. Log in as administrator and navigate to **'Financial Reports'**.
2. Generate commission report for the previous 2 weeks.
3. View report: total order value, 5% commission, 95% producer payment, and order count.
4. Select a specific order and view the detailed breakdown.
5. **Verification (Single):** For £100 order, verify £5.00 commission and £95.00 payout.
6. **Verification (Multi-vendor):** For £150 order (Producer A: £80, Producer B: £70), verify:
    * Total Commission: **£7.50** (5% of £150)
    * Producer A Payment: **£76.00** (95% of £80)
    * Producer B Payment: **£66.50** (95% of £70)
7. Download report in CSV/PDF format.

### Expected Results
* Admin can access comprehensive, auditable financial reports.
* Commission calculations are accurate to 2 decimal places.
* Multi-vendor logic correctly splits payments per supplier based on their items.
* Reports can be filtered by date, producer, or status.

### Acceptance Criteria
* Financial calculations comply with accounting standards.
* Commission split (5%/95%) is consistently applied.
* Audit trail links all calculations to source orders.
* System prevents unauthorised access to financial data.